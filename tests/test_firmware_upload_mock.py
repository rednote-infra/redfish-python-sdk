"""AMI action discovery, multipart encoding, task references, and errors."""

import json
import logging
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishException, RedfishValidationError
from redfish_sdk.models.common import Link
from redfish_sdk.models.update import (
    SoftwareInventory,
    UpdateParameters,
    UpdateService,
    UpdateServiceCapabilities,
)


def response(status=204, body=None, location=None, retry_after=None):
    result = requests.Response()
    result.request = requests.Request("POST", "https://mock-bmc/custom/action").prepare()
    result.status_code = status
    result._content = json.dumps(body).encode() if body is not None else b""
    if location:
        result.headers["Location"] = location
    if retry_after:
        result.headers["Retry-After"] = retry_after
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
        return response(
            202,
            {"@odata.id": "/custom/task/7", "Id": "7", "TaskState": "Running"},
            "/custom/monitor/7",
            "15",
        )

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
    assert result.task_uri == "/custom/task/7"
    assert result.retry_after == "15"


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

def test_capabilities_and_software_inventory_follow_advertised_links(firmware_client, monkeypatch):
    client, service = firmware_client
    service.update_service_capabilities = Link(odata_id="/custom/capabilities")
    service.software_inventory = Link(odata_id="/custom/software")
    capabilities = UpdateServiceCapabilities.model_validate(
        {
            "AllowableTargets": ["/custom/software/BMC"],
            "TargetsParameterSupported": True,
        }
    )
    inventory = [
        SoftwareInventory.model_validate(
            {
                "@odata.id": "/custom/software/BMC",
                "ImageState": "Armed",
                "OEMImageState": "AwaitingReset",
                "Active": False,
                "Staged": True,
                "Armed": True,
                "Links": {
                    "StagedTargets": [{"@odata.id": "/redfish/v1/Managers/1"}],
                    "ArmedTargets": [{"@odata.id": "/redfish/v1/Managers/1"}],
                },
            }
        )
    ]
    get = Mock(return_value=capabilities)
    collection = Mock(return_value=inventory)
    monkeypatch.setattr(client._http_client, "get", get)
    monkeypatch.setattr(client, "_get_collection", collection)

    assert client.get_update_service_capabilities() is capabilities
    assert client.get_software_inventory() == inventory
    get.assert_called_once_with("/custom/capabilities", UpdateServiceCapabilities)
    collection.assert_called_once_with("/custom/software", SoftwareInventory)
    assert inventory[0].image_state == "Armed"
    assert inventory[0].oem_image_state == "AwaitingReset"
    assert inventory[0].armed is True
    assert inventory[0].links.armed_targets[0].odata_id == "/redfish/v1/Managers/1"


@pytest.mark.parametrize(
    "argument,value,capability",
    [
        ("targets", ["/custom/software/BMC"], "Targets"),
        ("exclude_targets", ["/custom/software/Backup"], "ExcludeTargets"),
        ("force_update", False, "ForceUpdate"),
        ("stage", False, "Stage"),
        ("local_image", False, "LocalImage"),
    ],
)
def test_update_parameters_reject_requested_unsupported_options(
    firmware_client, monkeypatch, argument, value, capability
):
    client, service = firmware_client
    service.update_service_capabilities = Link(odata_id="/custom/capabilities")
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda *_: UpdateServiceCapabilities.model_validate(
            {
                "TargetsParameterSupported": False,
                "ExcludeTargetsParameterSupported": False,
                "ForceUpdateParameterSupported": False,
                "StageParameterSupported": False,
                "LocalImageParameterSupported": False,
            }
        ),
    )

    with pytest.raises(RedfishValidationError, match=capability):
        client.build_update_parameters(**{argument: value})


def test_update_parameters_validate_targets_and_preserve_false_values(firmware_client, monkeypatch):
    client, service = firmware_client
    service.update_service_capabilities = Link(odata_id="/custom/capabilities")
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda *_: UpdateServiceCapabilities.model_validate(
            {
                "AllowableTargets": ["/custom/software/BMC"],
                "AllowableStaging": ["/custom/software/BMC"],
                "TargetsParameterSupported": True,
                "ExcludeTargetsParameterSupported": True,
                "ForceUpdateParameterSupported": True,
                "StageParameterSupported": True,
                "LocalImageParameterSupported": True,
            }
        ),
    )

    parameters = client.build_update_parameters(
        targets=["/custom/software/BMC"],
        exclude_targets=["/custom/software/Backup"],
        force_update=False,
        stage=True,
        local_image=False,
    )

    assert parameters.model_dump(by_alias=True, exclude_none=True) == {
        "Targets": ["/custom/software/BMC"],
        "ExcludeTargets": ["/custom/software/Backup"],
        "ForceUpdate": False,
        "Stage": True,
        "LocalImage": False,
    }
    with pytest.raises(RedfishValidationError, match="AllowableStaging"):
        client.build_update_parameters(targets=["/custom/software/Backup"], stage=True)


def test_update_parameters_accept_advertised_standard_target_reference(firmware_client, monkeypatch):
    client, service = firmware_client
    service.update_service_capabilities = Link(odata_id="/custom/capabilities")
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda *_: UpdateServiceCapabilities.model_validate(
            {
                "AllowableTargetReferenceTypes": ["ComputerSystem"],
                "TargetsParameterSupported": True,
            }
        ),
    )
    monkeypatch.setattr(
        client._http_client,
        "get_raw",
        lambda target: {
            "@odata.id": target,
            "@odata.type": "#ComputerSystem.v1_25_0.ComputerSystem",
        },
    )

    parameters = client.build_update_parameters(targets=["/redfish/v1/Systems/1"])
    assert parameters.targets == ["/redfish/v1/Systems/1"]

    monkeypatch.setattr(
        client._http_client,
        "get_raw",
        lambda target: {
            "@odata.id": target,
            "@odata.type": "#Manager.v1_22_0.Manager",
        },
    )
    with pytest.raises(RedfishValidationError, match="target reference"):
        client.build_update_parameters(targets=["/redfish/v1/Managers/1"])


def test_optional_capabilities_are_only_required_for_gated_parameters(
    firmware_client, monkeypatch
):
    client, service = firmware_client
    service.update_service_capabilities = None
    service.actions["#UpdateService.SimpleUpdate"] = {
        "target": "/custom/simple-update"
    }
    request = Mock(return_value=response())
    monkeypatch.setattr(client._http_client, "post_raw", request)

    assert client.build_update_parameters() == UpdateParameters()
    client.standard_simple_update("https://images.example/fw.bin", "HTTPS")
    request.assert_called_once_with(
        "/custom/simple-update",
        {
            "ImageURI": "https://images.example/fw.bin",
            "TransferProtocol": "HTTPS",
        },
    )
    with pytest.raises(RedfishValidationError, match="UpdateServiceCapabilities"):
        client.build_update_parameters(force_update=True)
    with pytest.raises(RedfishValidationError, match="UpdateServiceCapabilities"):
        client.get_update_service_capabilities()

    service.software_inventory = None
    with pytest.raises(RedfishValidationError, match="SoftwareInventory"):
        client.get_software_inventory()


def test_typed_multipart_parameters_are_validated_and_serialized(
    firmware_client, monkeypatch, tmp_path
):
    client, service = firmware_client
    service.multi_part_http_push_uri = "/custom/multipart"
    service.update_service_capabilities = Link(odata_id="/custom/capabilities")
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda *_: UpdateServiceCapabilities.model_validate({
            "AllowableTargets": ["/custom/software/BMC"],
            "TargetsParameterSupported": True,
            "ForceUpdateParameterSupported": True,
        }),
    )
    request = Mock(return_value=response())
    monkeypatch.setattr(client._http_client, "_request", request)
    image = tmp_path / "fw.bin"
    image.write_bytes(b"firmware")

    client.upload_firmware_file(
        image,
        update_parameters=UpdateParameters(
            targets=["/custom/software/BMC"], force_update=False
        ),
    )

    parameters = multipart_parts(request.call_args.kwargs)[0]
    assert json.loads(parameters[2]) == {
        "Targets": ["/custom/software/BMC"],
        "ForceUpdate": False,
    }


def test_standard_stage_and_activate_use_advertised_actions(firmware_client, monkeypatch):
    client, service = firmware_client
    service.update_service_capabilities = Link(odata_id="/custom/capabilities")
    service.actions.update(
        {
            "#UpdateService.SimpleUpdate": {"target": "/custom/simple-update"},
            "#UpdateService.Activate": {"target": "/custom/activate"},
        }
    )
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda *_: UpdateServiceCapabilities.model_validate(
            {
                "AllowableTargets": ["/custom/software/BMC"],
                "AllowableStaging": ["/custom/software/BMC"],
                "TargetsParameterSupported": True,
                "StageParameterSupported": True,
            }
        ),
    )
    request = Mock(
        return_value=response(
            202,
            {"@odata.id": "/custom/task/12", "TaskState": "Running"},
            "/custom/monitor/12",
            "10",
        )
    )
    monkeypatch.setattr(client._http_client, "post_raw", request)

    staged = client.stage_update("https://images.example/fw.bin", ["/custom/software/BMC"])
    assert staged.task_monitor == "/custom/monitor/12"
    request.assert_called_with(
        "/custom/simple-update",
        {
            "ImageURI": "https://images.example/fw.bin",
            "TransferProtocol": "HTTPS",
            "Targets": ["/custom/software/BMC"],
            "Stage": True,
        },
    )

    client.activate_software(["/custom/software/BMC"])
    request.assert_called_with(
        "/custom/activate",
        {"Targets": [{"@odata.id": "/custom/software/BMC"}]},
    )
