"""Offline settings discovery, scheduling, and conditional BIOS updates."""
import json
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishException, RedfishValidationError
from redfish_sdk.models.common import Entity
from redfish_sdk.models.systems import System

BIOS = "/custom/bios/active"
PENDING = "/custom/config/pending"
MODES = ["Immediate", "OnReset", "AtMaintenanceWindowStart", "InMaintenanceWindowOnReset"]


def response(payload=None, status=200, etag=None):
    result = requests.Response()
    result.status_code = status
    result._content = b"" if payload is None else json.dumps(payload).encode()
    result.request = requests.Request("GET", "https://example.test/").prepare()
    if etag:
        result.headers["ETag"] = etag
    return result


@pytest.fixture
def bios_client(monkeypatch):
    with RedfishClient("example.test", "test", "test", verify_ssl=True) as client:
        system = System.model_validate({"Id": "Example", "Bios": {"@odata.id": BIOS}})
        monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)
        active = {"@odata.id": BIOS, "Attributes": {"Mode": "Active"}, "@Redfish.Settings": {
            "ETag": '"historical"', "SettingsObject": {"@odata.id": PENDING},
            "SupportedApplyTimes": MODES,
        }}
        pending = {"@odata.id": PENDING, "Attributes": {"Mode": "Pending"}}
        get = Mock(side_effect=lambda url, **kw: response(active if url.endswith(BIOS) else pending,
            etag='"active"' if url.endswith(BIOS) else '"pending"'))
        patch = Mock(return_value=response(status=204))
        monkeypatch.setattr(client._http_client._session, "get", get)
        monkeypatch.setattr(client._http_client._session, "patch", patch)
        yield client, active, pending, get, patch


def test_active_and_pending_settings_are_distinct(bios_client):
    client, _, _, get, patch = bios_client
    assert client.get_bios().attributes == {"Mode": "Active"}
    assert client.get_bios_settings().attributes == {"Mode": "Pending"}
    assert get.call_args.args[0].endswith(PENDING)
    patch.assert_not_called()


@pytest.mark.parametrize("mode", MODES)
def test_apply_times_and_etag_are_from_advertised_resources(bios_client, mode):
    from redfish_sdk import MaintenanceWindow
    client, _, _, get, patch = bios_client
    options = {}
    if "MaintenanceWindow" in mode:
        options["maintenance_window"] = MaintenanceWindow(
            maintenance_window_start_time="2026-12-01T10:00:00Z",
            maintenance_window_duration_in_seconds=120,
        )
    client.update_bios({"Mode": "New", "Enabled": False, "Count": 0}, apply_time=mode, **options)
    assert get.call_count == 2
    assert patch.call_args.args[0].endswith(PENDING)
    kwargs = patch.call_args.kwargs
    assert kwargs["headers"]["If-Match"] == '"pending"'
    assert kwargs["json"]["Attributes"] == {"Mode": "New", "Enabled": False, "Count": 0}
    schedule = kwargs["json"]["@Redfish.SettingsApplyTime"]
    assert schedule["ApplyTime"] == mode
    assert "@Redfish.OperationApplyTime" not in kwargs["json"]
    if options:
        assert schedule["MaintenanceWindowDurationInSeconds"] == 120
    assert patch.call_count == 1


def test_unspecified_apply_time_remains_unspecified(bios_client):
    client, _, pending, _, patch = bios_client
    pending["@Redfish.SettingsApplyTime"] = {"ApplyTime": "OnReset"}
    client.update_bios({"Mode": None})
    assert patch.call_args.kwargs["json"] == {"Attributes": {"Mode": None}}


@pytest.mark.parametrize("mode", ["Unknown", "OnTargetReset", "OnStartUpdateRequest", True, 1])
def test_invalid_settings_apply_time_does_not_write(bios_client, mode):
    client, _, _, _, patch = bios_client
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"}, apply_time=mode)
    patch.assert_not_called()


def test_unsupported_mode_does_not_write(bios_client):
    client, active, _, _, patch = bios_client
    active["@Redfish.Settings"]["SupportedApplyTimes"] = ["OnReset"]
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"}, apply_time="Immediate")
    patch.assert_not_called()


def test_no_advertised_apply_times_does_not_write(bios_client):
    client, active, _, _, patch = bios_client
    del active["@Redfish.Settings"]["SupportedApplyTimes"]
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"}, apply_time="Immediate")
    patch.assert_not_called()


def test_pending_allowable_values_are_respected(bios_client):
    client, _, pending, _, patch = bios_client
    pending["@Redfish.SettingsApplyTime"] = {"ApplyTime@Redfish.AllowableValues": ["OnReset"]}
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"}, apply_time="Immediate")
    client.update_bios({"Mode": "New"}, apply_time="OnReset")
    assert patch.call_count == 1


def test_absent_settings_annotation_remains_readable(bios_client):
    client, active, _, get, patch = bios_client
    del active["@Redfish.Settings"]
    assert client.get_bios().settings is None
    with pytest.raises(RedfishValidationError):
        client.get_bios_settings()
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"})
    assert all(call.args[0].endswith(BIOS) for call in get.call_args_list)
    patch.assert_not_called()


@pytest.mark.parametrize("mode", ["AtMaintenanceWindowStart", "InMaintenanceWindowOnReset"])
def test_window_required_before_write(bios_client, mode):
    client, _, _, _, patch = bios_client
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"}, apply_time=mode)
    patch.assert_not_called()


@pytest.mark.parametrize("start", ["bad-date", "2026-12-01T10:00:00", "2026-99-99T10:00:00Z",
                                   "2026-12-01 10:00:00+00:00", "20261201T100000+00:00"])
def test_invalid_window_start_rejected(bios_client, start):
    from redfish_sdk import MaintenanceWindow
    client, _, _, _, patch = bios_client
    window = MaintenanceWindow(maintenance_window_start_time=start, maintenance_window_duration_in_seconds=120)
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"}, apply_time="AtMaintenanceWindowStart", maintenance_window=window)
    patch.assert_not_called()


def test_window_without_window_apply_time_rejected(bios_client):
    from redfish_sdk import MaintenanceWindow
    client, _, _, _, patch = bios_client
    window = MaintenanceWindow(maintenance_window_start_time="2026-12-01T10:00:00Z",
                               maintenance_window_duration_in_seconds=120)
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"}, maintenance_window=window)
    patch.assert_not_called()


def test_etag_conflict_is_not_retried(bios_client):
    client, _, _, _, patch = bios_client
    patch.return_value = response({"error": {"message": "Settings changed."}}, status=412)
    with pytest.raises(RedfishException) as caught:
        client.update_bios({"Mode": "New"})
    assert caught.value.status_code == 412
    assert patch.call_count == 1


def test_stale_cached_etag_is_not_used(bios_client, monkeypatch):
    client, active, pending, _, patch = bios_client
    client._http_client._last_etag[PENDING] = '"stale"'
    monkeypatch.setattr(client._http_client._session, "get", Mock(side_effect=[response(active), response(pending)]))
    with pytest.raises(RedfishValidationError):
        client.update_bios({"Mode": "New"})
    patch.assert_not_called()


def test_body_etag_is_used_if_header_absent(bios_client, monkeypatch):
    client, active, pending, _, patch = bios_client
    pending["@odata.etag"] = 'W/"body"'
    monkeypatch.setattr(client._http_client._session, "get", Mock(side_effect=[response(active), response(pending)]))
    client.update_bios({"Mode": "New"})
    assert patch.call_args.kwargs["headers"]["If-Match"] == 'W/"body"'


def test_current_header_etag_takes_precedence_over_body(bios_client):
    client, _, pending, _, patch = bios_client
    pending["@odata.etag"] = '"older-body"'
    client.update_bios({"Mode": "New"})
    assert patch.call_args.kwargs["headers"]["If-Match"] == '"pending"'


@pytest.mark.parametrize("attributes", [{}, [], {1: "Bad"}])
def test_invalid_attributes_never_write(bios_client, attributes):
    client, _, _, _, patch = bios_client
    with pytest.raises(RedfishValidationError):
        client.update_bios(attributes)
    patch.assert_not_called()


def test_allowable_values_without_supported_apply_times(bios_client):
    client, active, pending, _, patch = bios_client
    del active["@Redfish.Settings"]["SupportedApplyTimes"]
    pending["@Redfish.SettingsApplyTime"] = {"ApplyTime@Redfish.AllowableValues": ["OnReset"]}
    client.update_bios({"Mode": "New"}, apply_time="OnReset")
    assert patch.call_count == 1


def test_settings_messages_and_forward_enum_values_remain_readable():
    from redfish_sdk.models.systems import Bios
    resource = Bios.model_validate({"@Redfish.Settings": {"ETag": '"historical"',
        "Time": "2026-01-01T00:00:00Z", "Messages": [{"MessageId": "Base.1.0.Success"}],
        "MaintenanceWindowResource": {"@odata.id": "/custom/window"},
        "SupportedApplyTimes": ["FutureMode"]},
        "@Redfish.SettingsApplyTime": {"ApplyTime": "FutureMode"}})
    assert resource.settings.messages[0].message_id == "Base.1.0.Success"
    assert resource.settings.etag == '"historical"'
    assert resource.settings_apply_time.apply_time == "FutureMode"


@pytest.mark.parametrize("duration", [-1, True, "120"])
def test_invalid_window_duration_is_rejected(duration):
    from pydantic import ValidationError

    from redfish_sdk import MaintenanceWindow
    with pytest.raises(ValidationError):
        MaintenanceWindow(maintenance_window_start_time="2026-12-01T10:00:00Z",
                          maintenance_window_duration_in_seconds=duration)


def test_common_annotations_are_typed_and_optional():
    from redfish_sdk import OperationApplyTime
    resource = Entity.model_validate({"@Redfish.Settings": {"SettingsObject": {"@odata.id": PENDING}},
        "@Redfish.SettingsApplyTime": {"ApplyTime": "OnReset"},
        "@Redfish.OperationApplyTime": "OnTargetReset",
        "@Redfish.OperationApplyTimeSupport": {"SupportedValues": ["OnTargetReset"],
            "MaintenanceWindowResource": {"@odata.id": "/custom/window"}},
        "@Redfish.MaintenanceWindow": {"MaintenanceWindowStartTime": "2026-12-01T10:00:00Z",
            "MaintenanceWindowDurationInSeconds": 0}})
    assert resource.settings.settings_object.odata_id == PENDING
    assert resource.settings_apply_time.apply_time == "OnReset"
    assert resource.operation_apply_time == OperationApplyTime.ON_TARGET_RESET
    assert resource.operation_apply_time_support.maintenance_window_resource.odata_id == "/custom/window"
    assert resource.maintenance_window.maintenance_window_duration_in_seconds == 0
