"""
Mock tests for SDK-GAP fill APIs.

Covers:
  - New model fields: Drive.actions / Drive.power_state, Log.actions,
    EventService.actions.
  - New BootOption model.
  - New manager / client methods: clear_system_log, drive_reset,
    drive_by_odata_id, submit_test_event, boot_options /
    set_boot_option_enabled, set_indicator_led, set_drive_indicator_led.

These tests never hit a real BMC; HTTP calls are stubbed via monkeypatch
on ``RedfishClient._http_client``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Type

import pytest

from redfish_sdk import (
    BootOption,
    Drive,
    EventService,
    Log,
    RedfishClient,
    RedfishValidationError,
    Subscription,
)
from redfish_sdk.exceptions import RedfishException
from redfish_sdk.models.systems import System

MOCK_HOST = os.environ.get("BMC_IP", "mock-bmc-host")
MOCK_USER = os.environ.get("BMC_USER", "mock-user")
MOCK_PASSWORD = os.environ.get("BMC_PASSWORD", "mock-password")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> RedfishClient:
    return RedfishClient(host=MOCK_HOST, username=MOCK_USER, password=MOCK_PASSWORD)


class _CallRecorder:
    """Records the last HTTP call routed through a stubbed method."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    @property
    def last(self) -> Dict[str, Any]:
        assert self.calls, "no call recorded"
        return self.calls[-1]


def _install_get_route(monkeypatch, client: RedfishClient, route: Dict[str, Any]) -> None:
    """Install a path->model-instance route on ``http_client.get``."""

    def fake_get(path: str, model_class: Type[Any]):
        if path not in route:
            raise AssertionError(f"unexpected GET {path}")
        payload = route[path]
        # Allow either a pre-built model or a raw dict.
        if isinstance(payload, model_class):
            return payload
        return model_class(**payload)

    monkeypatch.setattr(client._http_client, "get", fake_get)


# ---------------------------------------------------------------------------
# Model parsing — new fields
# ---------------------------------------------------------------------------


class TestModelFields:
    """Verify new fields parse from raw Redfish JSON."""

    def test_drive_actions_and_power_state(self):
        raw = {
            "@odata.id": "/redfish/v1/Chassis/1/Drives/0",
            "Id": "0",
            "Name": "Drive 0",
            "IndicatorLED": "Off",
            "PowerState": "On",
            "Actions": {
                "#Drive.Reset": {
                    "target": "/redfish/v1/Chassis/1/Drives/0/Actions/Drive.Reset",
                    "ResetType@Redfish.AllowableValues": [
                        "ForceOn",
                        "GracefulShutdown",
                        "PowerCycle",
                    ],
                }
            },
        }
        drive = Drive(**raw)
        assert drive.power_state == "On"
        assert drive.actions is not None
        assert (
            drive.actions["#Drive.Reset"]["target"]
            == "/redfish/v1/Chassis/1/Drives/0/Actions/Drive.Reset"
        )
        # Existing fields keep working.
        assert drive.indicator_led == "Off"

    def test_log_actions(self):
        raw = {
            "@odata.id": "/redfish/v1/Systems/1/LogServices/Log1",
            "Id": "Log1",
            "Name": "SEL Log",
            "Actions": {
                "#LogService.ClearLog": {
                    "target": "/redfish/v1/Systems/1/LogServices/Log1/Actions/LogService.ClearLog"
                }
            },
        }
        log = Log(**raw)
        assert log.actions is not None
        assert (
            log.actions["#LogService.ClearLog"]["target"].endswith(
                "/LogService.ClearLog"
            )
        )

    def test_event_service_actions(self):
        raw = {
            "@odata.id": "/redfish/v1/EventService",
            "Id": "EventService",
            "Name": "Event Service",
            "Subscriptions": {"@odata.id": "/redfish/v1/EventService/Subscriptions"},
            "Actions": {
                "#EventService.SubmitTestEvent": {
                    "target": "/redfish/v1/EventService/Actions/EventService.SubmitTestEvent",
                    "EventType@Redfish.AllowableValues": [
                        "Alert",
                        "StatusChange",
                    ],
                }
            },
        }
        es = EventService(**raw)
        assert es.actions is not None
        action = es.actions["#EventService.SubmitTestEvent"]
        assert action["target"].endswith("/EventService.SubmitTestEvent")
        assert "Alert" in action["EventType@Redfish.AllowableValues"]

    def test_boot_option(self):
        raw = {
            "@odata.id": "/redfish/v1/Systems/1/BootOptions/Boot0001",
            "Id": "Boot0001",
            "Name": "Boot0001",
            "BootOptionReference": "Boot0001",
            "BootOptionEnabled": True,
            "UefiDevicePath": "PciRoot(0x0)/Pci(0x14,0x0)/USB(0x9,0x0)",
            "DisplayName": "UEFI USB Key",
            "Alias": "Usb",
        }
        opt = BootOption(**raw)
        assert opt.boot_option_reference == "Boot0001"
        assert opt.boot_option_enabled is True
        assert opt.display_name == "UEFI USB Key"
        assert opt.alias == "Usb"


# ---------------------------------------------------------------------------
# SystemsManager — clear_system_log
# ---------------------------------------------------------------------------


class TestClearSystemLog:
    def _stub_system(self, monkeypatch, client: RedfishClient):
        from redfish_sdk.models.common import Link

        system = System.model_construct(
            id="1",
            odata_id="/redfish/v1/Systems/1",
            log_services=Link(**{"@odata.id": "/redfish/v1/Systems/1/LogServices"}),
        )
        monkeypatch.setattr(
            client._systems, "get", lambda system_id=None: system
        )
        return system

    def test_success(self, monkeypatch):
        client = _make_client()
        self._stub_system(monkeypatch, client)
        clear_target = (
            "/redfish/v1/Systems/1/LogServices/Log1/Actions/LogService.ClearLog"
        )

        # log_service() now goes through resolve_log_service which lists
        # the LogServices collection and picks by id.
        log = Log.model_construct(
            id="Log1",
            odata_id="/redfish/v1/Systems/1/LogServices/Log1",
            actions={"#LogService.ClearLog": {"target": clear_target}},
        )
        monkeypatch.setattr(
            client, "_get_collection",
            lambda odata_id, mc: [log] if mc is Log else [],
        )

        recorder = _CallRecorder()

        def fake_post(path, model_class, body=None, raw_body=None):
            recorder.record(path=path, raw_body=raw_body)
            return model_class.model_construct()

        monkeypatch.setattr(client._http_client, "post", fake_post)

        client.clear_system_log("Log1")
        assert recorder.last["path"] == clear_target
        assert recorder.last["raw_body"] == {}
        client.close()

    def test_no_action_raises(self, monkeypatch):
        client = _make_client()
        self._stub_system(monkeypatch, client)

        log = Log.model_construct(
            id="Log1",
            odata_id="/redfish/v1/Systems/1/LogServices/Log1",
            actions=None,
        )
        monkeypatch.setattr(
            client, "_get_collection",
            lambda odata_id, mc: [log] if mc is Log else [],
        )

        with pytest.raises(RedfishValidationError, match="ClearLog"):
            client.clear_system_log("Log1")
        client.close()


# ---------------------------------------------------------------------------
# SystemsManager — drive_reset / drive_by_odata_id
# ---------------------------------------------------------------------------


class TestDriveReset:
    def test_success(self, monkeypatch):
        client = _make_client()
        drive_id = "/redfish/v1/Chassis/1/Drives/0"
        reset_target = f"{drive_id}/Actions/Drive.Reset"
        drive = Drive.model_construct(
            id="0",
            odata_id=drive_id,
            actions={
                "#Drive.Reset": {
                    "target": reset_target,
                    "ResetType@Redfish.AllowableValues": [
                        "ForceOn",
                        "GracefulShutdown",
                    ],
                }
            },
        )
        monkeypatch.setattr(
            client._http_client, "get", lambda path, model_class: drive
        )

        recorder = _CallRecorder()

        def fake_post(path, model_class, body=None, raw_body=None):
            recorder.record(path=path, raw_body=raw_body)
            return model_class.model_construct()

        monkeypatch.setattr(client._http_client, "post", fake_post)

        client.drive_reset(drive_id, "GracefulShutdown")
        assert recorder.last["path"] == reset_target
        assert recorder.last["raw_body"] == {"ResetType": "GracefulShutdown"}
        client.close()

    def test_unknown_reset_type_rejected(self, monkeypatch):
        client = _make_client()
        drive_id = "/redfish/v1/Chassis/1/Drives/0"
        drive = Drive.model_construct(
            id="0",
            odata_id=drive_id,
            actions={
                "#Drive.Reset": {
                    "target": f"{drive_id}/Actions/Drive.Reset",
                    "ResetType@Redfish.AllowableValues": ["ForceOn"],
                }
            },
        )
        monkeypatch.setattr(
            client._http_client, "get", lambda path, model_class: drive
        )
        with pytest.raises(RedfishValidationError, match="not in allowable"):
            client.drive_reset(drive_id, "PowerCycle")
        client.close()

    def test_no_action_raises(self, monkeypatch):
        client = _make_client()
        drive_id = "/redfish/v1/Chassis/1/Drives/0"
        drive = Drive.model_construct(id="0", odata_id=drive_id, actions=None)
        monkeypatch.setattr(
            client._http_client, "get", lambda path, model_class: drive
        )
        with pytest.raises(RedfishValidationError, match="Drive.Reset"):
            client.drive_reset(drive_id, "GracefulShutdown")
        client.close()


class TestDriveByOdataId:
    def test_returns_parsed_drive(self, monkeypatch):
        client = _make_client()
        drive_id = "/redfish/v1/Systems/1/Storage/0/Drives/0"
        drive = Drive.model_construct(id="0", odata_id=drive_id, capacity_bytes=1024)

        captured: Dict[str, Any] = {}

        def fake_get(path, model_class):
            captured["path"] = path
            captured["model_class"] = model_class
            return drive

        monkeypatch.setattr(client._http_client, "get", fake_get)
        result = client.get_drive(drive_id)
        assert result is drive
        assert captured["path"] == drive_id
        assert captured["model_class"] is Drive
        client.close()


# ---------------------------------------------------------------------------
# EventServiceManager — submit_test_event / service
# ---------------------------------------------------------------------------


class TestEventService:
    def _stub_event_service(self, monkeypatch, client, actions):
        es = EventService.model_construct(
            id="EventService",
            odata_id="/redfish/v1/EventService",
            actions=actions,
        )
        monkeypatch.setattr(client, "_get_event_service", lambda: es)
        return es

    def test_service_returns_event_service(self, monkeypatch):
        client = _make_client()
        es = self._stub_event_service(
            monkeypatch, client, {"#EventService.SubmitTestEvent": {"target": "/x"}}
        )
        assert client.get_event_service() is es
        assert client.get_event_service().actions is not None
        client.close()

    def test_submit_test_event_success(self, monkeypatch):
        client = _make_client()
        target = "/redfish/v1/EventService/Actions/EventService.SubmitTestEvent"
        self._stub_event_service(
            monkeypatch,
            client,
            {
                "#EventService.SubmitTestEvent": {
                    "target": target,
                    "EventType@Redfish.AllowableValues": ["Alert", "StatusChange"],
                }
            },
        )

        recorder = _CallRecorder()

        def fake_post(path, model_class, body=None, raw_body=None):
            recorder.record(path=path, raw_body=raw_body)
            return model_class.model_construct()

        monkeypatch.setattr(client._http_client, "post", fake_post)

        client.submit_test_event(
            "Alert",
            message="hello",
            message_id="Base.1.0.Test",
            severity="OK",
            message_args=["a", "b"],
        )
        body = recorder.last["raw_body"]
        assert recorder.last["path"] == target
        assert body["EventType"] == "Alert"
        assert body["Message"] == "hello"
        assert body["MessageId"] == "Base.1.0.Test"
        assert body["Severity"] == "OK"
        assert body["MessageArgs"] == ["a", "b"]
        client.close()

    def test_submit_test_event_rejects_unknown_type(self, monkeypatch):
        client = _make_client()
        self._stub_event_service(
            monkeypatch,
            client,
            {
                "#EventService.SubmitTestEvent": {
                    "target": "/x",
                    "EventType@Redfish.AllowableValues": ["Alert"],
                }
            },
        )
        with pytest.raises(RedfishValidationError, match="not in allowable"):
            client.submit_test_event("Unsupported")
        client.close()

    def test_submit_test_event_no_action(self, monkeypatch):
        client = _make_client()
        self._stub_event_service(monkeypatch, client, None)
        with pytest.raises(RedfishValidationError, match="SubmitTestEvent"):
            client.submit_test_event("Alert")
        client.close()


# ---------------------------------------------------------------------------
# ChassisManager — IndicatorLED writes
# ---------------------------------------------------------------------------


class TestIndicatorLed:
    def test_invalid_state(self, monkeypatch):
        client = _make_client()
        with pytest.raises(RedfishValidationError, match="Invalid IndicatorLED"):
            client.set_indicator_led("Bogus")
        with pytest.raises(RedfishValidationError, match="Invalid IndicatorLED"):
            client.set_drive_indicator_led("/redfish/v1/Chassis/1/Drives/0", "Bogus")
        client.close()

    def test_chassis_set_indicator_led(self, monkeypatch):
        from redfish_sdk.models.chassis import Chassis

        client = _make_client()
        chassis_before = Chassis.model_construct(
            id="1",
            odata_id="/redfish/v1/Chassis/1",
            indicator_led="Off",
        )
        chassis_after = Chassis.model_construct(
            id="1",
            odata_id="/redfish/v1/Chassis/1",
            indicator_led="Lit",
        )
        # First get() returns "before" (refresh ETag), second returns "after".
        get_results = iter([chassis_before, chassis_after])
        monkeypatch.setattr(client._chassis, "get", lambda chassis_id="1": next(get_results))

        recorder = _CallRecorder()

        def fake_patch_raw(path, body, extra_headers=None):
            recorder.record(path=path, body=body)
            return None

        monkeypatch.setattr(client._http_client, "patch_raw", fake_patch_raw)
        result = client.set_indicator_led("Lit")
        assert result == "Lit"
        assert recorder.last == {"path": "/redfish/v1/Chassis/1", "body": {"IndicatorLED": "Lit"}}
        client.close()

    def test_drive_set_indicator_led(self, monkeypatch):
        client = _make_client()
        drive_id = "/redfish/v1/Chassis/1/Drives/0"
        before = Drive.model_construct(id="0", odata_id=drive_id, indicator_led="Off")
        after = Drive.model_construct(id="0", odata_id=drive_id, indicator_led="Blinking")
        get_results = iter([before, after])
        monkeypatch.setattr(
            client._http_client, "get",
            lambda path, model_class: next(get_results),
        )

        recorder = _CallRecorder()

        def fake_patch_raw(path, body, extra_headers=None):
            recorder.record(path=path, body=body)

        monkeypatch.setattr(client._http_client, "patch_raw", fake_patch_raw)
        result = client.set_drive_indicator_led(drive_id, "Blinking")
        assert result == "Blinking"
        assert recorder.last == {"path": drive_id, "body": {"IndicatorLED": "Blinking"}}
        client.close()


# ---------------------------------------------------------------------------
# SystemsManager — BootOptions collection
# ---------------------------------------------------------------------------


class TestBootOptions:
    @staticmethod
    def _system_with_boot_options() -> System:
        from redfish_sdk.models.common import Link
        from redfish_sdk.models.systems import Boot

        return System.model_construct(
            id="1",
            odata_id="/redfish/v1/Systems/1",
            boot=Boot(
                **{
                    "BootOptions": {
                        "@odata.id": "/redfish/v1/Systems/1/BootOptions"
                    }
                }
            ),
        )

    @staticmethod
    def _system_without_boot_options() -> System:
        from redfish_sdk.models.systems import Boot

        return System.model_construct(
            id="1",
            odata_id="/redfish/v1/Systems/1",
            boot=Boot(**{"BootSourceOverrideEnabled": "Disabled"}),
        )

    def test_boot_options_empty_when_link_missing(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            client._systems, "get", lambda system_id=None: self._system_without_boot_options()
        )
        assert client.get_boot_options() == []
        client.close()

    def test_boot_options_collection(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            client._systems, "get", lambda system_id=None: self._system_with_boot_options()
        )

        def fake_get_collection(path, model_class):
            assert path == "/redfish/v1/Systems/1/BootOptions"
            assert model_class is BootOption
            return [
                BootOption.model_construct(
                    id="Boot0001",
                    odata_id="/redfish/v1/Systems/1/BootOptions/Boot0001",
                    boot_option_enabled=True,
                ),
            ]

        monkeypatch.setattr(client, "_get_collection", fake_get_collection)
        opts = client.get_boot_options()
        assert len(opts) == 1
        assert opts[0].boot_option_enabled is True
        client.close()

    def test_boot_option_single(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            client._systems, "get", lambda system_id=None: self._system_with_boot_options()
        )

        option = BootOption.model_construct(
            id="Boot0001",
            odata_id="/redfish/v1/Systems/1/BootOptions/Boot0001",
            boot_option_enabled=False,
        )

        captured: Dict[str, Any] = {}

        def fake_get(path, model_class):
            captured["path"] = path
            assert model_class is BootOption
            return option

        monkeypatch.setattr(client._http_client, "get", fake_get)
        result = client.get_boot_option("Boot0001")
        assert result is option
        assert captured["path"] == "/redfish/v1/Systems/1/BootOptions/Boot0001"
        client.close()

    def test_set_boot_option_enabled(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            client._systems, "get", lambda system_id=None: self._system_with_boot_options()
        )

        option_id = "/redfish/v1/Systems/1/BootOptions/Boot0001"
        before = BootOption.model_construct(
            id="Boot0001", odata_id=option_id, boot_option_enabled=False
        )
        after = BootOption.model_construct(
            id="Boot0001", odata_id=option_id, boot_option_enabled=True
        )

        get_results = iter([before, after])
        monkeypatch.setattr(
            client._http_client, "get", lambda path, model_class: next(get_results)
        )

        recorder = _CallRecorder()

        def fake_patch_raw(path, body, extra_headers=None):
            recorder.record(path=path, body=body)

        monkeypatch.setattr(client._http_client, "patch_raw", fake_patch_raw)
        result = client.set_boot_option_enabled("Boot0001", True)
        assert result is after
        assert recorder.last == {"path": option_id, "body": {"BootOptionEnabled": True}}
        client.close()

    def test_boot_option_raises_when_no_collection(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            client._systems, "get",
            lambda system_id=None: self._system_without_boot_options(),
        )
        with pytest.raises(RedfishValidationError, match="BootOptions"):
            client.get_boot_option("Boot0001")
        client.close()


# ---------------------------------------------------------------------------
# Subscription model — http_headers polymorphism + new fields
# ---------------------------------------------------------------------------


class TestSubscriptionModel:
    """``Subscription.http_headers`` must accept both dict and list[dict]
    forms because different BMC vendors echo back different shapes."""

    def test_http_headers_as_dict(self):
        sub = Subscription(**{
            "@odata.id": "/redfish/v1/EventService/Subscriptions/1",
            "Id": "1",
            "Name": "Sub 1",
            "Destination": "https://my-server/events",
            "HttpHeaders": {
                "Content-Type": "Application/JSON",
                "X-Auth-Token": "abc",
            },
        })
        assert isinstance(sub.http_headers, dict)
        assert sub.http_headers["X-Auth-Token"] == "abc"

    def test_http_headers_as_list_of_dict(self):
        sub = Subscription(**{
            "@odata.id": "/redfish/v1/EventService/Subscriptions/2",
            "Id": "2",
            "Name": "Sub 2",
            "Destination": "https://my-server/events",
            "HttpHeaders": [
                {"X-Auth-Token": "abc"},
                {"OData-Version": "4.0"},
            ],
        })
        assert isinstance(sub.http_headers, list)
        assert sub.http_headers[0]["X-Auth-Token"] == "abc"

    def test_new_fields_parsing(self):
        sub = Subscription(**{
            "@odata.id": "/redfish/v1/EventService/Subscriptions/3",
            "Id": "3",
            "Name": "Sub 3",
            "Destination": "https://my-server/events",
            "OriginResources": [{"@odata.id": "/redfish/v1"}],
            "DeliveryRetryPolicy": "TerminateAfterRetries",
            "MessageIds": ["EventRegistry.1.0.FQXSPSE4032I"],
            "EventFormatType": "Event",
            "Severities": ["Warning", "Critical"],
        })
        assert sub.origin_resources == [{"@odata.id": "/redfish/v1"}]
        assert sub.delivery_retry_policy == "TerminateAfterRetries"
        assert sub.message_ids == ["EventRegistry.1.0.FQXSPSE4032I"]
        assert sub.event_format_type == "Event"
        assert sub.severities == ["Warning", "Critical"]


# ---------------------------------------------------------------------------
# EventServiceManager — get_subscription / subscribe / delete (CRUD)
# ---------------------------------------------------------------------------


class TestEventSubscriptionCrud:
    SUB_COLLECTION = "/redfish/v1/EventService/Subscriptions"

    def _stub_event_service(self, monkeypatch, client):
        es = EventService.model_construct(
            id="EventService",
            odata_id="/redfish/v1/EventService",
            subscriptions=type("L", (), {"odata_id": self.SUB_COLLECTION})(),
        )
        monkeypatch.setattr(client, "_get_event_service", lambda: es)

    # -- get_subscription -------------------------------------------------

    def test_get_subscription_by_id(self, monkeypatch):
        client = _make_client()
        self._stub_event_service(monkeypatch, client)
        captured: Dict[str, Any] = {}

        def fake_get(path, model_class):
            captured["path"] = path
            return Subscription.model_construct(id="1", odata_id=path)

        monkeypatch.setattr(client._http_client, "get", fake_get)
        result = client.get_subscription("1")
        assert captured["path"] == f"{self.SUB_COLLECTION}/1"
        assert result.id == "1"
        client.close()

    def test_get_subscription_by_odata_id(self, monkeypatch):
        client = _make_client()
        # If id_or_uri already absolute, _get_event_service must NOT be called.
        called = {"flag": False}
        monkeypatch.setattr(
            client,
            "_get_event_service",
            lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
        )
        called  # silence linter

        absolute = "/redfish/v1/EventService/Subscriptions/abc"
        captured: Dict[str, Any] = {}

        def fake_get(path, model_class):
            captured["path"] = path
            return Subscription.model_construct(id="abc", odata_id=path)

        monkeypatch.setattr(client._http_client, "get", fake_get)
        result = client.get_subscription(absolute)
        assert captured["path"] == absolute
        assert result.odata_id == absolute
        client.close()

    def test_get_subscription_rejects_empty(self, monkeypatch):
        client = _make_client()
        with pytest.raises(RedfishValidationError, match="non-empty"):
            client.get_subscription("")
        client.close()

    # -- delete -----------------------------------------------------------

    def test_delete_by_id_resolves_collection_path(self, monkeypatch):
        client = _make_client()
        self._stub_event_service(monkeypatch, client)
        captured: Dict[str, Any] = {}

        def fake_delete(path):
            captured["path"] = path
            return ""

        monkeypatch.setattr(client._http_client, "delete", fake_delete)
        client.delete_subscription("1")
        assert captured["path"] == f"{self.SUB_COLLECTION}/1"
        client.close()

    def test_delete_by_odata_id_passes_through(self, monkeypatch):
        client = _make_client()
        absolute = "/redfish/v1/EventService/Subscriptions/abc"
        monkeypatch.setattr(
            client,
            "_get_event_service",
            lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
        )
        captured: Dict[str, Any] = {}

        def fake_delete(path):
            captured["path"] = path
            return ""

        monkeypatch.setattr(client._http_client, "delete", fake_delete)
        client.delete_subscription(absolute)
        assert captured["path"] == absolute
        client.close()

    # -- subscribe --------------------------------------------------------

    def _install_post(self, monkeypatch, client):
        recorder = _CallRecorder()

        def fake_post(path, model_class, body=None, raw_body=None):
            recorder.record(path=path, raw_body=raw_body)
            return Subscription.model_construct(
                id="new", odata_id=f"{self.SUB_COLLECTION}/new"
            )

        monkeypatch.setattr(client._http_client, "post", fake_post)
        return recorder

    def test_subscribe_backward_compatible_positional(self, monkeypatch):
        """Legacy ``subscribe(dest, types, ctx)`` callers keep working."""
        client = _make_client()
        self._stub_event_service(monkeypatch, client)
        recorder = self._install_post(monkeypatch, client)

        client.subscribe("https://srv/events", ["Alert"], "ctx-1")
        body = recorder.last["raw_body"]
        assert recorder.last["path"] == self.SUB_COLLECTION
        assert body == {
            "Destination": "https://srv/events",
            "Protocol": "Redfish",
            "EventTypes": ["Alert"],
            "Context": "ctx-1",
        }
        client.close()

    def test_subscribe_payload_a_generic(self, monkeypatch):
        """Replicates the generic BMC payload (HttpHeaders as dict +
        OriginResources)."""
        client = _make_client()
        self._stub_event_service(monkeypatch, client)
        recorder = self._install_post(monkeypatch, client)

        client.subscribe(
            "https://srv/events",
            ["Alert"],
            context="eventService context",
            http_headers={
                "Content-Type": "Application/JSON",
                "OData-Version": "4.0",
                "X-Auth-Token": "token",
            },
            origin_resources=[{"@odata.id": "/redfish/v1"}],
        )
        body = recorder.last["raw_body"]
        assert body["HttpHeaders"] == {
            "Content-Type": "Application/JSON",
            "OData-Version": "4.0",
            "X-Auth-Token": "token",
        }
        assert body["OriginResources"] == [{"@odata.id": "/redfish/v1"}]
        assert body["Protocol"] == "Redfish"
        client.close()

    def test_subscribe_payload_b_http_headers_list(self, monkeypatch):
        """Replicates a BMC variant requiring HttpHeaders as list[dict]."""
        client = _make_client()
        self._stub_event_service(monkeypatch, client)
        recorder = self._install_post(monkeypatch, client)

        client.subscribe(
            "https://srv/events",
            ["Alert"],
            http_headers=[{"X-Auth-Token": "token"}],
        )
        body = recorder.last["raw_body"]
        assert body["HttpHeaders"] == [{"X-Auth-Token": "token"}]
        client.close()

    def test_subscribe_payload_c_full_fields(self, monkeypatch):
        """Replicates a BMC variant requiring SubscriptionType / RegistryPrefixes
        / DeliveryRetryPolicy / MessageIds without EventTypes."""
        client = _make_client()
        self._stub_event_service(monkeypatch, client)
        recorder = self._install_post(monkeypatch, client)

        client.subscribe(
            "https://srv/events",
            context="AlertOnly",
            subscription_type="RedfishEvent",
            registry_prefixes=["EventRegistry"],
            message_ids=["EventRegistry.1.0.FQXSPSE4032I"],
            delivery_retry_policy="TerminateAfterRetries",
        )
        body = recorder.last["raw_body"]
        assert "EventTypes" not in body
        assert body["SubscriptionType"] == "RedfishEvent"
        assert body["RegistryPrefixes"] == ["EventRegistry"]
        assert body["MessageIds"] == ["EventRegistry.1.0.FQXSPSE4032I"]
        assert body["DeliveryRetryPolicy"] == "TerminateAfterRetries"
        client.close()

    def test_subscribe_raw_body_overrides_everything(self, monkeypatch):
        """``raw_body`` replaces the auto-generated body entirely."""
        client = _make_client()
        self._stub_event_service(monkeypatch, client)
        recorder = self._install_post(monkeypatch, client)

        custom = {"Foo": "bar", "Destination": "x"}
        client.subscribe(
            "https://srv/events",
            ["Alert"],
            context="ctx",
            http_headers={"X-Auth-Token": "ignored"},
            raw_body=custom,
        )
        # The body must be exactly `custom`, with no merging of other kwargs.
        assert recorder.last["raw_body"] == custom
        client.close()

    def test_subscribe_extra_shallow_merge(self, monkeypatch):
        """``extra`` shallow-merges into the auto-generated body."""
        client = _make_client()
        self._stub_event_service(monkeypatch, client)
        recorder = self._install_post(monkeypatch, client)

        client.subscribe(
            "https://srv/events",
            ["Alert"],
            extra={"OemFoo": {"X": 1}},
        )
        body = recorder.last["raw_body"]
        assert body["OemFoo"] == {"X": 1}
        assert body["Destination"] == "https://srv/events"
        client.close()

    def test_subscribe_failure_propagates(self, monkeypatch):
        """When a payload is rejected, the SDK raises ``RedfishException``
        so callers can try a different payload shape."""
        client = _make_client()
        self._stub_event_service(monkeypatch, client)

        def fake_post(path, model_class, body=None, raw_body=None):
            raise RedfishException(400, "Bad payload")

        monkeypatch.setattr(client._http_client, "post", fake_post)
        with pytest.raises(RedfishException):
            client.subscribe("https://srv/events", ["Alert"])
        client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
