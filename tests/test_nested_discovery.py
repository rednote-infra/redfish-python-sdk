"""Nested resources follow advertised links while preserving legacy fallbacks."""

from unittest.mock import Mock

import pytest

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishValidationError
from redfish_sdk.models.account import Account
from redfish_sdk.models.common import Link
from redfish_sdk.models.cooling import ThermalSubsystem
from redfish_sdk.models.event import EventService, Subscription
from redfish_sdk.models.managers import Manager
from redfish_sdk.models.registry import Registry
from redfish_sdk.models.session import Session, SessionService
from redfish_sdk.models.storage import Storage, Volume
from redfish_sdk.models.systems import Boot, BootOption, Gpu, Memory, Processor, System
from redfish_sdk.models.task import Task, TaskService
from redfish_sdk.models.thermal import Fan, Thermal


@pytest.mark.parametrize(
    "method_name,resource_name,parent_kind,collection",
    [
        ("get_memory", "Memory", "Systems", True),
        ("get_bios", "Bios", "Systems", False),
        ("get_network_protocol", "NetworkProtocol", "Managers", False),
        ("get_virtual_media", "VirtualMedia", "Managers", True),
    ],
)
@pytest.mark.parametrize("advertised", [True, False])
def test_nested_resources_use_advertised_links_or_legacy_fallback(
    monkeypatch, method_name, resource_name, parent_kind, collection, advertised
):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    parent_url = f"/redfish/v1/{parent_kind}/Self"
    advertised_url = f"/redfish/v1/custom/{resource_name}"
    payload = {"@odata.id": parent_url, "Id": "Self"}
    if advertised:
        payload[resource_name] = {"@odata.id": advertised_url}
    parent_class = System if parent_kind == "Systems" else Manager
    parent = parent_class.model_validate(payload)
    manager = client._systems if parent_kind == "Systems" else client._managers
    monkeypatch.setattr(manager, "get", lambda identifier=None: parent)
    request = Mock(return_value=[] if collection else object())
    if collection:
        monkeypatch.setattr(client, "_get_collection", request)
    else:
        monkeypatch.setattr(client._http_client, "get", request)

    getattr(client, method_name)()

    assert request.call_args.args[0] == (advertised_url if advertised else f"{parent_url}/{resource_name}")
    client.close()


def test_manager_virtual_media_is_a_typed_link():
    manager = Manager.model_validate({"VirtualMedia": {"@odata.id": "/custom/media"}})
    assert manager.virtual_media.odata_id == "/custom/media"
    assert "VirtualMedia" not in (manager.model_extra or {})


def test_virtual_media_preserves_oem_fallback(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    manager = Manager.model_validate({
        "@odata.id": "/redfish/v1/Managers/Self",
        "Oem": {"Public": {"VirtualMedia": {"@odata.id": "/custom/oem-media"}}},
    })
    monkeypatch.setattr(client._managers, "get", lambda identifier=None: manager)
    request = Mock(return_value=[])
    monkeypatch.setattr(client, "_get_collection", request)
    client.get_virtual_media()
    assert request.call_args.args[0] == "/custom/oem-media"
    client.close()


def test_task_and_registry_lookup_use_advertised_member_uris(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    task = Task.model_construct(id="job-7", odata_id="/custom/jobs/current")
    registry = Registry.model_construct(
        id="Base.1.0", odata_id="/custom/registries/base-current"
    )
    task_service = TaskService.model_construct(
        tasks=Link.model_construct(odata_id="/custom/jobs")
    )
    monkeypatch.setattr(client, "_get_task_service", lambda: task_service)
    monkeypatch.setattr(client, "_get_registries_collection", lambda: [registry])
    monkeypatch.setattr(
        client,
        "_get_collection",
        lambda path, model: [task] if path == "/custom/jobs" else pytest.fail(path),
    )
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda path, model: task
        if path == "/custom/jobs/current"
        else pytest.fail(f"constructed member request: {path}"),
    )

    assert client.get_task("job-7") is task
    assert client.get_task("/custom/jobs/current") is task
    assert client.get_registry("Base.1.0") is registry
    assert client.get_registry("/custom/registries/base-current") is registry
    client.close()


def test_member_lookup_reports_ambiguous_ids(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    task_service = TaskService.model_construct(
        tasks=Link.model_construct(odata_id="/custom/jobs")
    )
    tasks = [
        Task.model_construct(id="duplicate", odata_id="/custom/jobs/a"),
        Task.model_construct(id="duplicate", odata_id="/custom/jobs/b"),
    ]
    monkeypatch.setattr(client, "_get_task_service", lambda: task_service)
    monkeypatch.setattr(client, "_get_collection", lambda path, model: tasks)

    with pytest.raises(RedfishValidationError, match="unique @odata.id"):
        client.get_task("duplicate")
    client.close()


def test_task_lookup_keeps_incomplete_collection_compatibility_fallback(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    task_service = TaskService.model_construct(
        tasks=Link.model_construct(odata_id="/legacy/tasks")
    )
    task = Task.model_construct(id="7", odata_id="/legacy/tasks/7")
    request = Mock(return_value=task)
    monkeypatch.setattr(client, "_get_task_service", lambda: task_service)
    monkeypatch.setattr(client, "_get_collection", lambda path, model: [])
    monkeypatch.setattr(client._http_client, "get", request)

    assert client.get_task("7") is task
    request.assert_called_once_with("/legacy/tasks/7", Task)
    client.close()


def test_system_member_accessors_use_advertised_collections(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    system = System.model_construct(
        odata_id="/custom/system-node",
        processors=Link.model_construct(odata_id="/custom/cpu-inventory"),
        memory=Link.model_construct(odata_id="/custom/dimm-inventory"),
        boot=Boot.model_construct(
            boot_options=Link.model_construct(odata_id="/custom/boot-choices")
        ),
    )
    processor = Processor.model_validate(
        {"Id": "CPU0", "@odata.id": "/custom/cpus/socket-a"}
    )
    memory = Memory.model_validate(
        {"Id": "DIMM0", "@odata.id": "/custom/dimms/channel-a"}
    )
    boot_option = BootOption.model_construct(
        id="Boot0001", odata_id="/custom/options/network"
    )
    resources = {
        "/custom/cpu-inventory": [processor],
        "/custom/dimm-inventory": [memory],
        "/custom/boot-choices": [boot_option],
    }
    monkeypatch.setattr(client._systems, "get", lambda identifier=None: system)
    monkeypatch.setattr(client, "_get_collection", lambda path, model: resources[path])
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda path, model: pytest.fail(f"constructed member request: {path}"),
    )

    assert client.get_processor("CPU0") is processor
    assert client.get_processor("/custom/cpus/socket-a") is processor
    assert client.get_memory_device("DIMM0") is memory
    assert client.get_boot_option("Boot0001") is boot_option
    client.close()


def test_gpu_collection_uses_the_advertised_link(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    system = System.model_construct(
        odata_id="/custom/system-node",
        graphics_controllers=Link.model_construct(
            odata_id="/custom/gpu-inventory"
        ),
    )
    gpu = Gpu.model_construct(id="GPU0", odata_id="/custom/gpus/accelerator-a")
    request = Mock(return_value=[gpu])
    monkeypatch.setattr(client._systems, "get", lambda identifier=None: system)
    monkeypatch.setattr(client, "_get_collection", request)

    assert client.get_gpus() == [gpu]
    request.assert_called_once_with("/custom/gpu-inventory", Gpu)
    client.close()


def test_explicit_system_id_resolves_the_advertised_member(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    system = System.model_construct(id="Self", odata_id="/custom/system-node")
    monkeypatch.setattr(client, "_get_systems_collection", lambda: [system])
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda path, model: pytest.fail(f"constructed member request: {path}"),
    )

    assert client.get_system("Self") is system
    assert client.get_system("/custom/system-node") is system
    client.close()


def test_volumes_follow_storage_member_and_advertised_volumes_links(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    system = System.model_construct(
        odata_id="/custom/system-node",
        storage=Link.model_construct(odata_id="/custom/storage-inventory"),
    )
    storage = Storage.model_construct(
        id="RAID", odata_id="/custom/controllers/primary",
        volumes=Link.model_construct(odata_id="/custom/volume-inventory"),
    )
    volume = Volume.model_construct(id="volume-1", odata_id="/custom/volumes/one")
    requests = []

    def get_collection(path, model):
        requests.append(path)
        if path == "/custom/storage-inventory":
            return [storage]
        if path == "/custom/volume-inventory":
            return [volume]
        pytest.fail(path)

    monkeypatch.setattr(client._systems, "get", lambda identifier=None: system)
    monkeypatch.setattr(client, "_get_collection", get_collection)

    assert client.get_volumes("RAID") == [volume]
    assert requests == ["/custom/storage-inventory", "/custom/volume-inventory"]
    client.close()


def test_volumes_keep_member_relative_legacy_fallback_when_link_is_missing(
    monkeypatch,
):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    system = System.model_construct(
        storage=Link.model_construct(odata_id="/custom/storage-inventory")
    )
    storage = Storage.model_construct(
        id="RAID", odata_id="/custom/controllers/primary", volumes=None
    )
    requests = []

    def get_collection(path, model):
        requests.append(path)
        return [storage] if path == "/custom/storage-inventory" else []

    monkeypatch.setattr(client._systems, "get", lambda identifier=None: system)
    monkeypatch.setattr(client, "_get_collection", get_collection)

    assert client.get_volumes("RAID") == []
    assert requests == [
        "/custom/storage-inventory",
        "/custom/controllers/primary/Volumes",
    ]
    client.close()


def test_account_session_and_subscription_mutations_use_advertised_uris(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    account = Account.model_construct(
        id="42", user_name="operator", odata_id="/custom/accounts/operator-current"
    )
    session = Session.model_construct(id="7", odata_id="/custom/sessions/current")
    subscription = Subscription.model_construct(
        id="9", odata_id="/custom/subscriptions/alerts"
    )
    session_service = SessionService.model_construct(
        sessions=Link.model_construct(odata_id="/custom/sessions")
    )
    event_service = EventService.model_construct(
        subscriptions=Link.model_construct(odata_id="/custom/subscriptions")
    )
    monkeypatch.setattr(client._accounts, "accounts", lambda: [account])
    monkeypatch.setattr(client._sessions, "sessions", lambda: [session])
    monkeypatch.setattr(client._events, "subscriptions", lambda: [subscription])
    monkeypatch.setattr(client, "_get_session_service", lambda: session_service)
    monkeypatch.setattr(client, "_get_event_service", lambda: event_service)
    patch = Mock(return_value=account)
    delete = Mock(return_value="")
    monkeypatch.setattr(client._http_client, "patch", patch)
    monkeypatch.setattr(client._http_client, "delete", delete)

    account_patch = Account(enabled=False)
    assert client.update_account("operator", account_patch) is account
    client.delete_account("operator")
    assert client.get_session("7") is session
    client.delete_session("7")
    assert client.get_subscription("9") is subscription
    client.delete_subscription("9")

    assert patch.call_args.args[0] == "/custom/accounts/operator-current"
    assert [call.args[0] for call in delete.call_args_list] == [
        "/custom/accounts/operator-current",
        "/custom/sessions/current",
        "/custom/subscriptions/alerts",
    ]
    client.close()


def test_fans_follow_thermal_subsystem_and_fans_links(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    chassis = type("ChassisStub", (), {
        "odata_id": "/custom/chassis-node",
        "thermal_subsystem": Link.model_construct(
            odata_id="/custom/thermal-subsystem"
        ),
    })()
    subsystem = ThermalSubsystem.model_construct(
        fans=Link.model_construct(odata_id="/custom/fan-inventory")
    )
    fan = Fan.model_construct(id="fan-a", odata_id="/custom/fans/intake")
    requests = []

    def get(path, model):
        requests.append(path)
        assert path == "/custom/thermal-subsystem"
        return subsystem

    def get_collection(path, model):
        requests.append(path)
        assert path == "/custom/fan-inventory"
        return [fan]

    monkeypatch.setattr(client, "get_chassis", lambda identifier=None: chassis)
    monkeypatch.setattr(client._http_client, "get", get)
    monkeypatch.setattr(client, "_get_collection", get_collection)
    monkeypatch.setattr(
        client,
        "get_thermal",
        lambda identifier=None: Thermal.model_construct(fans=[]),
    )

    assert client.get_fan() == [fan]
    assert requests == ["/custom/thermal-subsystem", "/custom/fan-inventory"]
    client.close()
