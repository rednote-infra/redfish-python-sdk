"""Optional AMI system resources follow advertised Self resource hierarchies."""

import json
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishNotFoundError, RedfishValidationError
from redfish_sdk.models.system_resources import SecureBoot
from redfish_sdk.models.systems import System


@pytest.fixture
def resource_client(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    system = System.model_validate({
        "Id": "Self", "@odata.id": "/redfish/v1/Systems/Self",
        "SecureBoot": {"@odata.id": "/custom/secure"},
        "NetworkInterfaces": {"@odata.id": "/custom/interfaces"},
        "MemoryDomains": {"@odata.id": "/custom/domains"},
        "Memory": {"@odata.id": "/custom/memory"},
    })
    resources = {
        "/custom/secure": {
            "Id": "SecureBoot", "@odata.id": "/custom/secure", "@odata.etag": '"secure-etag"',
            "SecureBootEnable": True, "SecureBootMode": "UserMode",
            "Actions": {"#SecureBoot.ResetKeys": {"target": "/custom/reset-keys", "ResetKeysType@Redfish.AllowableValues": ["ResetAllKeysToDefault", "DeletePK"]}},
        },
        "/custom/interface": {"Id": "nic", "@odata.id": "/custom/interface", "NetworkPorts": {"@odata.id": "/custom/ports"}},
        "/custom/port": {"Id": "port", "@odata.id": "/custom/port", "CurrentLinkSpeedMbps": 10000, "LinkStatus": "LinkUp", "AssociatedNetworkAddresses": ["00:11:22:33:44:55"]},
        "/custom/domain": {"Id": "domain", "@odata.id": "/custom/domain", "MemoryChunks": {"@odata.id": "/custom/chunks"}, "InterleavableMemorySets": [{"MemorySet": [{"@odata.id": "/custom/dimm"}]}]},
        "/custom/chunk": {"Id": "chunk", "@odata.id": "/custom/chunk", "MemoryChunkSizeMiB": 1024, "InterleaveSets": [{"Memory": {"@odata.id": "/custom/dimm"}, "SizeMiB": 1024}]},
        "/custom/dimm": {"Id": "dimm", "@odata.id": "/custom/dimm", "Metrics": {"@odata.id": "/custom/metrics"}},
        "/custom/metrics": {"Id": "metrics", "@odata.id": "/custom/metrics", "CurrentPeriod": {"BlocksRead": 7}, "HealthData": {"AlarmTrips": {"Temperature": False}, "PredictedMediaLifeLeftPercent": 98}},
    }
    collections = {
        "/custom/interfaces": ["/custom/interface"], "/custom/ports": ["/custom/port"],
        "/custom/domains": ["/custom/domain"], "/custom/chunks": ["/custom/chunk"],
        "/custom/memory": ["/custom/dimm"],
    }
    monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)
    monkeypatch.setattr(client._http_client, "get_raw", lambda path: {"Members": [{"@odata.id": member} for member in collections[path]]})

    def request(method, path, **kwargs):
        assert method == "GET"
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(resources[path]).encode()
        response.headers["ETag"] = '"secure-etag"' if path == "/custom/secure" else '"resource-etag"'
        return response

    monkeypatch.setattr(client._http_client, "_request", request)
    yield client, system, resources, collections
    client.close()


def test_secure_boot_get_and_patch(resource_client, monkeypatch):
    client, _, _, _ = resource_client
    assert client.get_secure_boot().secure_boot_enable is True
    original_request = client._http_client._request
    patches = []

    def request(method, path, **kwargs):
        if method == "GET":
            return original_request(method, path, **kwargs)
        patches.append((method, path, kwargs))
        response = requests.Response()
        response.status_code = 204
        response._content = b""
        return response

    monkeypatch.setattr(client._http_client, "_request", request)
    client.update_secure_boot(False)
    method, path, parameters = patches[0]
    assert (method, path) == ("PATCH", "/custom/secure")
    assert parameters["json"] == {"SecureBootEnable": False}
    assert parameters["headers"]["If-Match"] == '"secure-etag"'


def test_secure_boot_reset_keys_and_validation(resource_client, monkeypatch):
    client, _, resources, _ = resource_client
    post = Mock()
    monkeypatch.setattr(client._http_client, "post", post)
    client.reset_secure_boot_keys("DeletePK")
    assert post.call_args.args[0] == "/custom/reset-keys"
    assert post.call_args.kwargs["body"].model_dump(by_alias=True) == {"ResetKeysType": "DeletePK"}
    with pytest.raises(RedfishValidationError, match="ResetKeysType"):
        client.reset_secure_boot_keys("DeleteAllKeys")
    resources["/custom/secure"]["Actions"] = {}
    with pytest.raises(RedfishValidationError, match="ResetKeys"):
        client.reset_secure_boot_keys("DeletePK")
    assert post.call_count == 1


def test_network_interfaces_and_ports(resource_client):
    client, _, _, _ = resource_client
    assert client.get_network_interfaces()[0].id == "nic"
    port = client.get_network_ports()[0]
    assert port.current_link_speed_mbps == 10000
    assert port.associated_network_addresses == ["00:11:22:33:44:55"]
    assert client.get_network_ports("nic")[0].odata_id == "/custom/port"
    assert client.get_network_port("port").odata_id == "/custom/port"
    assert client.get_network_port("/custom/port", "nic").id == "port"


def test_network_port_link_through_advertised_adapter(resource_client):
    client, _, resources, _ = resource_client
    resources["/custom/interface"].pop("NetworkPorts")
    resources["/custom/interface"]["Links"] = {"NetworkAdapter": {"@odata.id": "/custom/adapter"}}
    resources["/custom/adapter"] = {"@odata.id": "/custom/adapter", "NetworkPorts": {"@odata.id": "/custom/ports"}}
    assert client.get_network_ports()[0].id == "port"


def test_memory_domains_chunks_and_metrics(resource_client):
    client, _, _, _ = resource_client
    domain = client.get_memory_domain("domain")
    assert domain.interleavable_memory_sets[0].memory_set[0].odata_id == "/custom/dimm"
    chunk = client.get_memory_chunks("domain")[0]
    assert chunk.memory_chunk_size_mib == 1024
    assert chunk.interleave_sets[0].memory.odata_id == "/custom/dimm"
    assert client.get_memory_chunk("chunk").odata_id == "/custom/chunk"
    metrics = client.get_memory_metrics("dimm")
    assert metrics.current_period.blocks_read == 7
    assert metrics.health_data.alarm_trips.temperature is False


@pytest.mark.parametrize("field,method", [
    ("secure_boot", "get_secure_boot"), ("network_interfaces", "get_network_ports"),
    ("memory_domains", "get_memory_domains"), ("memory", "get_memory_metrics"),
])
def test_missing_optional_capability_preserves_system(resource_client, field, method):
    client, system, _, _ = resource_client
    setattr(system, field, None)
    with pytest.raises(RedfishNotFoundError):
        getattr(client, method)()
    assert client.get_system().id == "Self"


@pytest.mark.parametrize("parent,field,method", [
    ("/custom/interface", "NetworkPorts", "get_network_ports"),
    ("/custom/domain", "MemoryChunks", "get_memory_chunks"),
    ("/custom/dimm", "Metrics", "get_memory_metrics"),
])
def test_missing_nested_capability(resource_client, parent, field, method):
    client, _, resources, _ = resource_client
    resources[parent].pop(field)
    with pytest.raises(RedfishNotFoundError, match=field):
        getattr(client, method)()


def test_empty_advertised_collections(resource_client):
    client, _, _, collections = resource_client
    collections["/custom/ports"] = []
    collections["/custom/chunks"] = []
    assert client.get_network_ports() == []
    assert client.get_memory_chunks() == []


def test_ambiguous_memory_ids_require_full_uri(resource_client):
    client, _, resources, collections = resource_client
    resources["/custom/dimm2"] = {"Id": "dimm", "@odata.id": "/custom/dimm2", "Metrics": {"@odata.id": "/custom/metrics"}}
    collections["/custom/memory"].append("/custom/dimm2")
    with pytest.raises(RedfishValidationError, match="Multiple"):
        client.get_memory_metrics("dimm")
    assert client.get_memory_metrics("/custom/dimm2").id == "metrics"


def test_secure_boot_action_info_and_enable_constraints(resource_client, monkeypatch):
    client, _, resources, _ = resource_client
    action = resources["/custom/secure"]["Actions"]["#SecureBoot.ResetKeys"]
    action.pop("ResetKeysType@Redfish.AllowableValues")
    action["@Redfish.ActionInfo"] = "/custom/keys-info"
    resources["/custom/keys-info"] = {"Parameters": [{"Name": "ResetKeysType", "AllowableValues": ["DeletePK"]}]}
    post = Mock()
    monkeypatch.setattr(client._http_client, "post", post)
    with pytest.raises(RedfishValidationError, match="ResetKeysType"):
        client.reset_secure_boot_keys("ResetAllKeysToDefault")
    client.reset_secure_boot_keys("DeletePK")
    assert post.call_count == 1
    resources["/custom/secure"]["SecureBootEnable@Redfish.AllowableValues"] = [True]
    with pytest.raises(RedfishValidationError, match="SecureBootEnable"):
        client.update_secure_boot(False)


def test_secure_boot_actions_are_typed_and_preserve_vendor_fields():
    resource = SecureBoot.model_validate({"Actions": {
        "#SecureBoot.ResetKeys": {
            "target": "/custom/keys", "@Redfish.ActionInfo": "/custom/info",
            "ResetKeysType@Redfish.AllowableValues": ["DeletePK"], "VendorFlag": True,
        },
        "Oem": {"#AMI.KeyAction": {"target": "/custom/vendor"}},
    }})
    action = resource.actions.reset_keys
    assert action.target == "/custom/keys"
    assert action.action_info == "/custom/info"
    assert action.reset_keys_type_allowable_values == ["DeletePK"]
    payload = resource.model_dump(by_alias=True, exclude_none=True)["Actions"]
    assert payload["#SecureBoot.ResetKeys"]["VendorFlag"] is True
    assert payload["Oem"]["#AMI.KeyAction"]["target"] == "/custom/vendor"


@pytest.mark.parametrize("descriptor", [None, {}, {"target": 7}, {"target": ""}, "invalid"])
def test_invalid_secure_boot_action_has_clear_capability_error(resource_client, descriptor):
    client, _, resources, _ = resource_client
    resources["/custom/secure"]["Actions"] = {"#SecureBoot.ResetKeys": descriptor}
    with pytest.raises(RedfishValidationError, match="ResetKeys"):
        client.reset_secure_boot_keys("DeletePK")
