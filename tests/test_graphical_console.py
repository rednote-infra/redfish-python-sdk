"""Standard ComputerSystem graphical-console models and actions."""

import logging
from unittest.mock import MagicMock

import pytest
import requests

from redfish_sdk.exceptions import RedfishException, RedfishValidationError
from redfish_sdk.http_client import RedfishHttpClient
from redfish_sdk.managers.systems import SystemsManager
from redfish_sdk.models.actions import ActionInfo
from redfish_sdk.models.common import RedfishResponse
from redfish_sdk.models.systems import (
    GraphicalConsoleGetOneTimeURLResponse,
    GraphicalConsoleSetOneTimePasswordResponse,
    System,
)


def _system() -> System:
    return System.model_validate({
        "@odata.id": "/redfish/v1/Systems/1",
        "Id": "1",
        "Manufacturer": "Example",
        "Model": "Server",
        "SerialNumber": "serial",
        "PowerState": "On",
        "GraphicalConsole": {
            "ConnectTypesSupported": ["KVMIP"],
            "MaxConcurrentSessions": 4,
            "VendorField": "preserved",
            "VNC": {
                "ServiceEnabled": True,
                "SupportedAccessModes": ["ReadWrite", "ReadOnly"],
                "SupportsOneTimePassword": True,
                "SupportsPersistentPassword": True,
                "SupportedEncodings": ["Hextile"],
            },
            "RDP": {"ServiceEnabled": True, "SupportedAccessModes": ["ReadOnly"]},
            "HTML5": {
                "ServiceEnabled": True,
                "SupportedAccessModes": ["ReadWrite"],
                "SupportsOneTimeURL": True,
                "ConsoleURI": "/console",
            },
            "KVMIP": {"ServiceEnabled": True},
        },
        "Actions": {
            "#ComputerSystem.GraphicalConsoleGetOneTimeURL": {
                "target": "/custom/console/url",
                "ConsoleType@Redfish.AllowableValues": ["HTML5"],
                "AccessMode@Redfish.AllowableValues": ["ReadWrite"],
                "ValidityPeriodSeconds@Redfish.AllowableValues": [60, 120],
            },
            "#ComputerSystem.GraphicalConsoleSetOneTimePassword": {
                "target": "/custom/console/otp",
                "ConsoleType@Redfish.AllowableValues": ["VNC"],
            },
            "#ComputerSystem.GraphicalConsoleSetPassword": {
                "target": "/custom/console/password",
                "ConsoleType@Redfish.AllowableValues": ["VNC"],
            },
        },
    })


def _manager(system=None):
    client = MagicMock()
    client._http_client = MagicMock()
    manager = SystemsManager(client)
    manager.get = MagicMock(return_value=system or _system())
    return manager, client._http_client


def test_models_all_protocols_and_preserves_legacy_and_unknown_fields():
    console = _system().graphical_console

    assert console.connect_types_supported == ["KVMIP"]
    assert console.vnc.supported_encodings == ["Hextile"]
    assert console.rdp.supported_access_modes == ["ReadOnly"]
    assert console.html5.console_uri == "/console"
    assert console.kvmip.service_enabled is True
    assert console.model_extra["VendorField"] == "preserved"


def test_get_one_time_url_uses_custom_target_and_typed_response():
    manager, http = _manager()
    expected = GraphicalConsoleGetOneTimeURLResponse.model_validate({
        "ConsoleType": "HTML5",
        "AccessMode": "ReadWrite",
        "ConsoleURL": "https://bmc/console?token=secret",
    })
    http.post.return_value = expected

    result = manager.graphical_console_get_one_time_url(
        "HTML5", "ReadWrite", 60
    )

    assert result is expected
    path, response_type = http.post.call_args.args
    request = http.post.call_args.kwargs["body"]
    assert path == "/custom/console/url"
    assert response_type is GraphicalConsoleGetOneTimeURLResponse
    assert request.model_dump(by_alias=True, exclude_none=True) == {
        "ConsoleType": "HTML5",
        "AccessMode": "ReadWrite",
        "ValidityPeriodSeconds": 60,
    }


def test_one_time_and_persistent_password_actions_are_typed():
    manager, http = _manager()
    response = GraphicalConsoleSetOneTimePasswordResponse.model_validate({
        "ConsoleType": "VNC", "AccessMode": "ReadOnly", "Password": "generated"
    })
    http.post.side_effect = [response, RedfishResponse()]

    assert manager.graphical_console_set_one_time_password(
        "VNC", "ReadOnly", "requested", 30
    ).password == "generated"
    assert http.post.call_args_list[0].args[0] == "/custom/console/otp"
    assert http.post.call_args_list[0].kwargs["body"].password == "requested"

    manager.graphical_console_set_password("VNC", "persistent")
    assert http.post.call_args_list[1].args[0] == "/custom/console/password"
    assert http.post.call_args_list[1].kwargs["body"].password == "persistent"


@pytest.mark.parametrize(
    ("console_type", "access_mode", "validity", "message"),
    [
        ("VNC", "ReadWrite", 60, "ConsoleType"),
        ("HTML5", "ReadOnly", 60, "AccessMode"),
        ("HTML5", "ReadWrite", 30, "ValidityPeriodSeconds"),
    ],
)
def test_rejects_parameters_outside_advertised_values(
    console_type, access_mode, validity, message
):
    manager, http = _manager()

    with pytest.raises(RedfishValidationError, match=message):
        manager.graphical_console_get_one_time_url(
            console_type, access_mode, validity
        )
    http.post.assert_not_called()


def test_rejects_absent_graphical_console_and_action():
    system = _system()
    system.graphical_console = None
    manager, http = _manager(system)

    with pytest.raises(RedfishValidationError, match="does not advertise"):
        manager.graphical_console_get_one_time_url()
    http.post.assert_not_called()

    system = _system()
    system.actions.graphical_console_get_one_time_url = None
    manager, http = _manager(system)
    with pytest.raises(RedfishValidationError, match="does not expose"):
        manager.graphical_console_get_one_time_url()
    http.post.assert_not_called()


def test_action_info_constraints_are_discovered():
    system = _system()
    action = system.actions.graphical_console_get_one_time_url
    action.console_type_allowable_values = None
    action.access_mode_allowable_values = None
    action.validity_period_seconds_allowable_values = None
    action.action_info = "/custom/console/action-info"
    manager, http = _manager(system)
    http.get.return_value = ActionInfo.model_validate({
        "Parameters": [
            {"Name": "ConsoleType", "AllowableValues": ["HTML5"]},
            {"Name": "AccessMode", "AllowableValues": ["ReadWrite"]},
            {"Name": "ValidityPeriodSeconds", "MinimumValue": 30, "MaximumValue": 90},
        ]
    })
    http.post.return_value = GraphicalConsoleGetOneTimeURLResponse.model_validate({
        "ConsoleType": "HTML5", "AccessMode": "ReadWrite",
        "ConsoleURL": "https://bmc/console?token=secret",
    })

    manager.graphical_console_get_one_time_url("HTML5", "ReadWrite", 60)
    http.get.assert_called_once_with("/custom/console/action-info", ActionInfo)

    with pytest.raises(RedfishValidationError, match="at most 90"):
        manager.graphical_console_get_one_time_url("HTML5", "ReadWrite", 120)

def _response(status, body):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode()
    response.headers["Content-Type"] = "application/json"
    response.request = requests.Request("POST", "https://bmc/action").prepare()
    return response


def test_http_logs_redact_password_and_sensitive_console_url(caplog):
    http = RedfishHttpClient("bmc", "user", "password")
    http._session.post = MagicMock(return_value=_response(400, (
        '{"Password":"response-secret",'
        '"ConsoleURL":"https://bmc/console?token=url-secret"}'
    )))
    caplog.set_level(logging.INFO)

    with pytest.raises(RedfishException) as exc_info:
        http.post_raw("/action", {
            "Password": "request-secret",
            "Nested": {"Token": "nested-secret"},
        })

    combined = caplog.text + str(exc_info.value)
    assert "request-secret" not in combined
    assert "response-secret" not in combined
    assert "url-secret" not in combined
    assert "nested-secret" not in combined
    assert "<redacted>" in combined


def test_http_logs_redact_tokens_embedded_in_request_urls(caplog):
    http = RedfishHttpClient("bmc", "user", "password")
    http._session.get = MagicMock(return_value=_response(200, "{}"))
    caplog.set_level(logging.INFO)

    http.download("https://bmc/console?token=url-secret")

    assert "url-secret" not in caplog.text
    assert "%3Credacted%3E" in caplog.text
