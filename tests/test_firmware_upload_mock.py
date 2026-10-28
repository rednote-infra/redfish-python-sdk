"""AMI action discovery, multipart encoding, task references, and errors."""

import json
import logging
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishException, RedfishValidationError
from redfish_sdk.models.update import UpdateService


def response(status=204, body=None, location=None):
    result = requests.Response()
    result.request = requests.Request("POST", "https://mock-bmc/custom/action").prepare()
    result.status_code = status
    result._content = json.dumps(body).encode() if body is not None else b""
    if location:
        result.headers["Location"] = location
    return result


def multipart_parts(arguments):
    """Return ordered multipart headers and bodies from a prepared request."""
    content_type = arguments["headers"]["Content-Type"]
    boundary = content_type.split("boundary=", 1)[1].encode()
    result = []
    for raw_part in arguments["data"].split(b"--" + boundary)[1:-1]:
        header_block, body = raw_part.strip(b"\r\n").split(b"\r\n\r\n", 1)
        headers = header_block.decode("utf-8")
        name = headers.split('name="', 1)[1].split('"', 1)[0]
        result.append((name, headers, body.rstrip(b"\r\n")))
    return result


@pytest.fixture
def firmware_client(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    service = UpdateService.model_validate({
        "@odata.id": "/custom/update", "HttpPushUri": "/custom/push",
        "Actions": {"Oem": {
            "#UpdateService.UploadSignKey": {"target": "/custom/key"},
            "#UpdateService.UploadFirmwareImage": {"target": "/custom/image"},
            "#UpdateService.BMCFwUpdate": {"target": "/custom/flash", "FlashType@Redfish.AllowableValues": ["FULLFwUpdate", "DUALIMAGEFwUpdate"]},
        }},
    })
    monkeypatch.setattr(client, "_get_update_service", lambda: service)
    yield client, service
    client.close()


@pytest.mark.parametrize("method,field,target", [
    ("upload_sign_key", "pem_file", "/custom/key"),
    ("upload_firmware_image", "image_file", "/custom/image"),
    ("upload_firmware_file", "UpdateFile", "/custom/push"),
])
def test_upload_multipart_and_no_sensitive_logging(firmware_client, monkeypatch, tmp_path, caplog, method, field, target):
    client, _ = firmware_client
    image_path = tmp_path / "firmware.bin"
    image_path.write_bytes(b"PRIVATE-FIRMWARE-CONTENT")
    captured = []

    def request(verb, path, **arguments):
        captured.append((verb, path, arguments))
        return response(202, {"@odata.id": "/custom/task/7", "Id": "7", "TaskState": "Running"}, "/custom/monitor/7")

    monkeypatch.setattr(client._http_client, "_request", request)
    with caplog.at_level(logging.INFO, logger="redfish_sdk"):
        result = getattr(client, method)(image_path)
    verb, path, arguments = captured[0]
    assert (verb, path) == ("POST", target)
    assert arguments["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert f'name="{field}"'.encode() in arguments["data"]
    assert b"PRIVATE-FIRMWARE-CONTENT" in arguments["data"]
    assert str(image_path) not in caplog.text
    assert "PRIVATE-FIRMWARE-CONTENT" not in caplog.text
    assert result.odata_id == "/custom/task/7"
    assert result.task_id == "7"
    assert result.task_monitor == "/custom/monitor/7"
    assert result.http_status == 202


def test_standard_multipart_push_parameters(
    firmware_client, monkeypatch, tmp_path, caplog
):
    client, service = firmware_client
    service.multi_part_http_push_uri = "/custom/multipart"
    image = tmp_path / "fw.bin"
    image.write_bytes(b"firmware")
    request = Mock(return_value=response())
    monkeypatch.setattr(client._http_client, "_request", request)
    with caplog.at_level(logging.INFO, logger="redfish_sdk"):
        client.upload_firmware_file(
            image,
            update_parameters={
                "Targets": ["/custom/bmc"],
                "Password": "SENSITIVE-PARAMETER",
            },
            oem_parameters={"PreserveConfiguration": True},
        )
    assert request.call_args.args == ("POST", "/custom/multipart")
    arguments = request.call_args.kwargs
    parts = multipart_parts(arguments)
    assert [part[0] for part in parts] == [
        "UpdateParameters",
        "OemParameters",
        "UpdateFile",
    ]
    assert sum(part[0] == "UpdateParameters" for part in parts) == 1
    assert "Content-Type: application/json" in parts[0][1]
    assert json.loads(parts[0][2]) == {
        "Targets": ["/custom/bmc"],
        "Password": "SENSITIVE-PARAMETER",
    }
    assert parts[1][0].startswith("Oem")
    assert "Content-Type: application/json" in parts[1][1]
    assert json.loads(parts[1][2]) == {"PreserveConfiguration": True}
    assert 'filename="fw.bin"' in parts[2][1]
    assert "Content-Type: application/octet-stream" in parts[2][1]
    assert parts[2][2] == b"firmware"
    assert "SENSITIVE-PARAMETER" not in caplog.text
    assert str(image) not in caplog.text


def test_standard_multipart_push_includes_empty_parameters(
    firmware_client, monkeypatch, tmp_path
):
    client, service = firmware_client
    service.multi_part_http_push_uri = "/custom/multipart"
    image = tmp_path / "fw.bin"
    image.write_bytes(b"firmware")
    request = Mock(return_value=response())
    monkeypatch.setattr(client._http_client, "_request", request)

    client.upload_firmware_file(image)

    parts = multipart_parts(request.call_args.kwargs)
    assert [part[0] for part in parts] == ["UpdateParameters", "UpdateFile"]
    assert "Content-Type: application/json" in parts[0][1]
    assert json.loads(parts[0][2]) == {}


@pytest.mark.parametrize("flash_type,selector", [("FULLFwUpdate", None), ("DUALIMAGEFwUpdate", "ImageBoth")])
def test_bmc_firmware_update_payload(firmware_client, monkeypatch, flash_type, selector):
    client, _ = firmware_client
    request = Mock(return_value=response(202, location="/custom/monitor/9"))
    monkeypatch.setattr(client._http_client, "_request", request)
    result = client.bmc_firmware_update(flash_type, upload_selector=selector)
    expected = {"FlashType": flash_type}
    if selector is not None:
        expected["UploadSelector"] = selector
    assert request.call_args.args == ("POST", "/custom/flash")
    assert request.call_args.kwargs["json"] == expected
    assert result.task_monitor == "/custom/monitor/9"


@pytest.mark.parametrize("flash_type,selector", [("DUALIMAGEFwUpdate", None), ("unknown", None), ("DUALIMAGEFwUpdate", "unknown")])
def test_firmware_update_validation(firmware_client, monkeypatch, flash_type, selector):
    client, _ = firmware_client
    request = Mock()
    monkeypatch.setattr(client._http_client, "_request", request)
    with pytest.raises(RedfishValidationError):
        client.bmc_firmware_update(flash_type, upload_selector=selector)
    request.assert_not_called()


def test_unsupported_action_does_not_open_file(firmware_client):
    client, service = firmware_client
    service.actions = None
    with pytest.raises(RedfishValidationError, match="UploadSignKey"):
        client.upload_sign_key("nonexistent-private-path.pem")
    service.http_push_uri = None
    with pytest.raises(RedfishValidationError, match="PushUri"):
        client.upload_firmware_file("nonexistent-private-path.bin")


def test_upload_errors_propagate(firmware_client, monkeypatch, tmp_path):
    client, _ = firmware_client
    image = tmp_path / "fw.bin"
    image.write_bytes(b"firmware")
    monkeypatch.setattr(client._http_client, "_request", lambda *args, **kwargs: response(400, {"error": {"code": "Rejected", "message": "Image rejected"}}))
    with pytest.raises(RedfishException) as error:
        client.upload_firmware_image(image)
    assert error.value.status_code == 400


def test_standard_multipart_push_errors_propagate(
    firmware_client, monkeypatch, tmp_path
):
    client, service = firmware_client
    service.multi_part_http_push_uri = "/custom/multipart"
    image = tmp_path / "fw.bin"
    image.write_bytes(b"firmware")
    monkeypatch.setattr(
        client._http_client,
        "_request",
        lambda *args, **kwargs: response(
            400, {"error": {"code": "Rejected", "message": "Image rejected"}}
        ),
    )

    with pytest.raises(RedfishException) as error:
        client.upload_firmware_file(image)

    assert error.value.status_code == 400


@pytest.mark.parametrize("standard_push", [False, True], ids=["ami-action", "standard-push"])
def test_multipart_retry_reuses_complete_body(
    firmware_client, monkeypatch, tmp_path, standard_push
):
    client, service = firmware_client
    client._http_client.retry_5xx = 1
    client._http_client.retry_backoff = 0
    image = tmp_path / "fw.bin"
    image.write_bytes(b"full-firmware")
    calls = []

    def post(url, **arguments):
        calls.append(arguments)
        return response(503 if len(calls) == 1 else 204)

    monkeypatch.setattr(client._http_client._session, "post", post)
    if standard_push:
        service.multi_part_http_push_uri = "/custom/multipart"
        client.upload_firmware_file(image)
    else:
        client.upload_firmware_image(image)
    assert len(calls) == 2
    assert calls[0]["data"] == calls[1]["data"]
    assert b"full-firmware" in calls[1]["data"]
    if standard_push:
        assert [part[0] for part in multipart_parts(calls[1])] == [
            "UpdateParameters",
            "UpdateFile",
        ]


def test_action_info_allowable_values_are_respected(firmware_client, monkeypatch):
    client, service = firmware_client
    action = service.actions["Oem"]["#UpdateService.BMCFwUpdate"]
    action.pop("FlashType@Redfish.AllowableValues")
    action["@Redfish.ActionInfo"] = "/custom/action-info"
    monkeypatch.setattr(client._http_client, "get_raw", lambda path: {"Parameters": [{"Name": "FlashType", "AllowableValues": ["DUALIMAGEFwUpdate"]}]})
    with pytest.raises(RedfishValidationError, match="FlashType"):
        client.bmc_firmware_update("FULLFwUpdate")


def test_ambiguous_or_missing_action_targets_are_rejected(firmware_client):
    client, service = firmware_client
    service.actions["#AMIUpdateService.UploadSignKey"] = {"target": "/custom/other-key"}
    with pytest.raises(RedfishValidationError, match="unique"):
        client.upload_sign_key("not-opened.pem")
    service.actions = {"#UpdateService.UploadSignKey": {"title": "Unsupported"}}
    with pytest.raises(RedfishValidationError, match="target"):
        client.upload_sign_key("not-opened.pem")
