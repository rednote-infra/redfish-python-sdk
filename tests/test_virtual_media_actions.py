"""Standard VirtualMedia InsertMedia and EjectMedia actions."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from redfish_sdk.exceptions import RedfishException, RedfishValidationError
from redfish_sdk.http_client import RedfishHttpClient
from redfish_sdk.managers.managers import ManagersManager
from redfish_sdk.models.actions import ActionInfo
from redfish_sdk.models.common import RedfishResponse
from redfish_sdk.models.managers import VirtualMedia

TESTDATA_DIR = Path(__file__).parent.parent / "testdata"


def _fixture(name: str) -> dict:
    with (TESTDATA_DIR / "virtual_media.json").open(encoding="utf-8") as fixture:
        return json.load(fixture)[name]


def _media(name: str = "NewMedia") -> VirtualMedia:
    return VirtualMedia.model_validate(_fixture(name))


def _manager(media=None):
    client = MagicMock()
    client._http_client = MagicMock()
    manager = ManagersManager(client)
    manager.virtual_media = MagicMock(return_value=[media or _media()])
    return manager, client._http_client


def test_models_new_and_legacy_virtual_media_payloads():
    media = _media()
    assert media.http_headers.root == {}
    assert media.write_protected is True
    assert media.eject_policy == "OnPowerOff"
    assert media.actions.insert_media.target == "/custom/media/insert"
    assert media.model_extra["VendorField"] == "preserved"

    legacy = _media("LegacyMedia")
    assert legacy.image == "https://images.example/legacy.iso"
    assert legacy.http_headers is None
    assert legacy.actions is None
    assert legacy.model_extra["LegacyVendorField"] is True


def test_insert_media_uses_advertised_target_and_optional_http_headers():
    manager, http = _manager()
    http.post.return_value = RedfishResponse.model_validate(
        _fixture("AsyncResponse")
    )

    result = manager.insert_virtual_media(
        "https://images.example/os.iso",
        media_id="CD1",
        transfer_method="Stream",
        transfer_protocol_type="HTTPS",
        inserted=True,
        write_protected=True,
        username="image-user",
        password="image-password",
        http_headers={"Authorization": "Bearer image-token"},
    )

    assert result.task_monitor == "/redfish/v1/TaskService/TaskMonitors/42"
    target, response_type = http.post.call_args.args
    request = http.post.call_args.kwargs["body"]
    assert target == "/custom/media/insert"
    assert response_type is RedfishResponse
    assert request.model_dump(by_alias=True, exclude_none=True) == {
        "Image": "https://images.example/os.iso",
        "Inserted": True,
        "WriteProtected": True,
        "UserName": "image-user",
        "Password": "image-password",
        "TransferMethod": "Stream",
        "TransferProtocolType": "HTTPS",
        "HTTPHeaders": {"Authorization": "Bearer image-token"},
    }


def test_insert_media_discovers_action_info_and_rejects_unsupported_values():
    media = _media()
    media.http_headers = None
    action = media.actions.insert_media
    action.transfer_method_allowable_values = None
    action.transfer_protocol_type_allowable_values = None
    action.action_info = "/custom/media/insert-info"
    manager, http = _manager(media)
    http.get.return_value = ActionInfo.model_validate(_fixture("ActionInfo"))

    with pytest.raises(RedfishValidationError, match="TransferProtocolType"):
        manager.insert_virtual_media(
            "https://images.example/os.iso",
            transfer_method="Stream",
            transfer_protocol_type="FTP",
        )
    http.post.assert_not_called()

    manager.insert_virtual_media(
        "https://images.example/os.iso",
        transfer_method="Stream",
        transfer_protocol_type="HTTPS",
        http_headers={"X-Image-Token": "token"},
    )
    http.get.assert_called_with("/custom/media/insert-info", ActionInfo)


def test_insert_media_rejects_unadvertised_headers_and_missing_action():
    media = _media()
    media.http_headers = None
    media.actions.insert_media.action_info = None
    manager, http = _manager(media)

    with pytest.raises(RedfishValidationError, match="HTTPHeaders"):
        manager.insert_virtual_media(
            "https://images.example/os.iso",
            http_headers={"Authorization": "Bearer token"},
        )
    http.post.assert_not_called()

    media = _media()
    media.actions.insert_media = None
    manager, http = _manager(media)
    with pytest.raises(RedfishValidationError, match="#VirtualMedia.InsertMedia"):
        manager.insert_virtual_media("https://images.example/os.iso")
    http.post.assert_not_called()

    media = _media()
    media.actions.eject_media = None
    manager, http = _manager(media)
    with pytest.raises(RedfishValidationError, match="#VirtualMedia.EjectMedia"):
        manager.eject_virtual_media()
    http.post.assert_not_called()


def test_insert_media_validates_header_names_and_protocol():
    manager, http = _manager()

    with pytest.raises(ValueError, match="Invalid HTTP header name"):
        manager.insert_virtual_media(
            "https://images.example/os.iso",
            http_headers={"Invalid Header": "value"},
        )

    with pytest.raises(RedfishValidationError, match="HTTPHeaders.*HTTP or HTTPS"):
        manager.insert_virtual_media(
            "smb://images.example/os.iso",
            transfer_protocol_type="CIFS",
            http_headers={"Authorization": "Bearer token"},
        )
    http.post.assert_not_called()


def test_eject_media_uses_advertised_target_and_preserves_async_response():
    manager, http = _manager()
    expected = RedfishResponse.model_validate(_fixture("AsyncResponse"))
    http.post.return_value = expected

    result = manager.eject_virtual_media("CD1")

    assert result is expected
    target, response_type = http.post.call_args.args
    assert target == "/custom/media/eject"
    assert response_type is RedfishResponse
    assert http.post.call_args.kwargs["body"].model_dump() == {}


def test_media_actions_propagate_http_errors():
    manager, http = _manager()
    http.post.side_effect = RedfishException(503, "BMC is busy")

    with pytest.raises(RedfishException, match="BMC is busy"):
        manager.eject_virtual_media("CD1")


def test_virtual_media_discovery_does_not_perform_media_actions():
    manager, http = _manager()

    assert manager.virtual_media_resource("CD1").id == "CD1"
    http.post.assert_not_called()


def _response(status: int, body: dict) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    response.request = requests.Request("POST", "https://bmc/action").prepare()
    return response


def test_http_logs_redact_image_credentials_and_caller_supplied_headers(caplog):
    http = RedfishHttpClient("bmc", "bmc-user", "bmc-password")
    http._session.post = MagicMock(
        return_value=_response(400, _fixture("SensitiveError"))
    )
    caplog.set_level(logging.INFO)

    with pytest.raises(RedfishException):
        http.post_raw("/insert", {
            "Image": "https://image-user:image-password@images.example/os.iso?token=url-token",
            "UserName": "image-user",
            "Password": "image-password",
            "HTTPHeaders": {
                "Authorization": "Bearer image-token",
                "Cookie": "session=image-cookie",
            },
        })

    for secret in (
        "image-user", "image-password", "url-token", "image-token",
        "image-cookie", "response-token",
    ):
        assert secret not in caplog.text


def test_image_fetch_headers_are_not_added_to_bmc_session():
    http = RedfishHttpClient("bmc", "bmc-user", "bmc-password")
    original_authorization = http._session.headers["Authorization"]
    http._session.post = MagicMock(return_value=_response(204, {}))

    http.post_raw("/insert", {
        "Image": "https://images.example/os.iso",
        "HTTPHeaders": {"Authorization": "Bearer image-token"},
    })

    assert http._session.headers["Authorization"] == original_authorization
    assert "Cookie" not in http._session.headers
    assert http._session.post.call_args.kwargs["json"]["HTTPHeaders"] == {
        "Authorization": "Bearer image-token"
    }
