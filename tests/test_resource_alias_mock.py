"""Typed resource aliases, capability checks, and alias-based addressing."""

import json
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishException, RedfishValidationError
from redfish_sdk.models.root import RootService
from redfish_sdk.models.systems import BootOption, System


def response(status=200, body=None, headers=None):
    result = requests.Response()
    result.request = requests.Request(
        "PATCH", "https://mock-bmc/redfish/v1/Systems/1"
    ).prepare()
    result.status_code = status
    result._content = json.dumps(body).encode() if body is not None else b""
    result.headers.update(headers or {})
    return result


@pytest.fixture
def client(monkeypatch):
    value = RedfishClient(host="mock-bmc", username="user", password="password")
    root = RootService.model_validate({
        "@odata.id": "/redfish/v1/",
        "ProtocolFeaturesSupported": {"Alias": True},
    })
    monkeypatch.setattr(value, "_get_root", lambda: root)
    yield value
    value.close()


def test_alias_models_are_typed_and_boot_option_alias_remains_independent():
    option = BootOption.model_validate({
        "@odata.id": "/redfish/v1/Systems/1/BootOptions/Boot0001",
        "Id": "Boot0001",
        "Alias": "Usb",
        "@Redfish.Alias": "installation-media",
    })
    root = RootService.model_validate({
        "ProtocolFeaturesSupported": {
            "Alias": True,
            "FutureProtocolFeature": {"Enabled": True},
        }
    })

    assert option.alias == "Usb"
    assert option.redfish_alias == "installation-media"
    assert option.model_dump(by_alias=True, exclude_none=True)["Alias"] == "Usb"
    assert option.model_dump(by_alias=True, exclude_none=True)["@Redfish.Alias"] == "installation-media"
    assert root.protocol_features_supported.alias is True
    assert root.protocol_features_supported.model_extra["FutureProtocolFeature"] == {
        "Enabled": True
    }


def test_older_payloads_without_alias_support_still_parse():
    root = RootService.model_validate({
        "@odata.id": "/redfish/v1/",
        "RedfishVersion": "1.8.0",
        "Systems": {"@odata.id": "/redfish/v1/Systems"},
    })
    system = System.model_validate({
        "@odata.id": "/redfish/v1/Systems/1",
        "Id": "1",
        "Manufacturer": "Example",
        "Model": "Server",
        "SerialNumber": "serial",
        "PowerState": "On",
    })

    assert root.protocol_features_supported is None
    assert system.redfish_alias is None
    assert system.odata_id == "/redfish/v1/Systems/1"


def test_set_resource_alias_uses_resource_etag_and_surfaces_reassignment(
    client, monkeypatch
):
    resource = System.model_validate({
        "@odata.id": "/redfish/v1/Systems/1",
        "@odata.etag": 'W/"before"',
        "Id": "1",
        "@Redfish.Alias": "old-name",
    })
    patch = Mock(return_value=response(
        200,
        {
            "@Message.ExtendedInfo": [{
                "MessageId": "Base.1.19.AliasValueReassigned",
                "Message": "The alias was reassigned from another resource.",
                "MessageArgs": ["primary-system"],
            }]
        },
        {"ETag": 'W/"after"'},
    ))
    monkeypatch.setattr(client._http_client, "patch_raw", patch)

    updated = client.set_resource_alias(resource, "primary-system")

    patch.assert_called_once_with(
        "/redfish/v1/Systems/1",
        {"@Redfish.Alias": "primary-system"},
        extra_headers={"If-Match": 'W/"before"'},
    )
    assert isinstance(updated, System)
    assert updated.redfish_alias == "primary-system"
    assert updated.odata_etag == 'W/"after"'
    assert updated.extended_info[0].message_id.endswith("AliasValueReassigned")


def test_set_resource_alias_fetches_etag_and_clear_uses_empty_string(
    client, monkeypatch
):
    resource = System.model_construct(
        id="1", odata_id="/redfish/v1/Systems/1", redfish_alias="primary-system"
    )
    refreshed = resource.model_copy(update={"odata_etag": 'W/"current"'})
    get = Mock(return_value=refreshed)
    patch = Mock(return_value=response(204))
    monkeypatch.setattr(client._http_client, "get", get)
    monkeypatch.setattr(client._http_client, "patch_raw", patch)

    updated = client.clear_resource_alias(resource)

    get.assert_called_once_with("/redfish/v1/Systems/1", System)
    patch.assert_called_once_with(
        "/redfish/v1/Systems/1",
        {"@Redfish.Alias": ""},
        extra_headers={"If-Match": 'W/"current"'},
    )
    assert updated.redfish_alias == ""


@pytest.mark.parametrize(
    "alias",
    ["", "~system", "contains space", "slash/name", "percent%20name", "中文"],
)
def test_alias_addressing_rejects_invalid_values(client, alias):
    with pytest.raises(RedfishValidationError, match="resource alias"):
        client.get_resource_by_alias(
            "/redfish/v1/Systems", alias, System
        )


def test_alias_assignment_rejects_invalid_values_before_request(client, monkeypatch):
    patch = Mock()
    monkeypatch.setattr(client._http_client, "patch_raw", patch)
    resource = System.model_construct(odata_id="/redfish/v1/Systems/1")

    with pytest.raises(RedfishValidationError, match="resource alias"):
        client.set_resource_alias(resource, "invalid/name")

    patch.assert_not_called()


def test_alias_mutation_requires_advertised_capability(client, monkeypatch):
    unsupported = RootService.model_validate({
        "ProtocolFeaturesSupported": {"Alias": False}
    })
    monkeypatch.setattr(client, "_get_root", lambda: unsupported)
    patch = Mock()
    monkeypatch.setattr(client._http_client, "patch_raw", patch)

    with pytest.raises(
        RedfishValidationError,
        match="does not advertise ProtocolFeaturesSupported.Alias",
    ):
        client.set_resource_alias(
            System.model_construct(odata_id="/redfish/v1/Systems/1"),
            "primary-system",
        )

    patch.assert_not_called()


def test_get_resource_by_alias_supports_nested_alias_paths(client, monkeypatch):
    resource = System.model_construct(
        id="1",
        odata_id="/redfish/v1/Systems/1/Processors/CPU1",
        redfish_alias="boot-cpu",
    )
    get = Mock(return_value=resource)
    monkeypatch.setattr(client._http_client, "get", get)

    result = client.get_resource_by_alias(
        "/redfish/v1/Systems/~primary-system/Processors",
        "boot-cpu",
        System,
    )

    assert result is resource
    assert client.resource_alias_uri(
        "/redfish/v1/Systems/~primary-system/Processors", "boot-cpu"
    ) == "/redfish/v1/Systems/~primary-system/Processors/~boot-cpu"
    get.assert_called_once_with(
        "/redfish/v1/Systems/~primary-system/Processors/~boot-cpu",
        System,
    )


def test_service_uniqueness_error_remains_actionable(client, monkeypatch):
    resource = System.model_construct(
        odata_id="/redfish/v1/Systems/1", odata_etag='W/"one"'
    )
    body = json.dumps({
        "error": {
            "code": "Base.1.19.PropertyValueConflict",
            "@Message.ExtendedInfo": [{
                "MessageId": "Base.1.19.PropertyValueConflict",
                "Message": "The alias is already assigned.",
            }],
        }
    })
    monkeypatch.setattr(
        client._http_client,
        "patch_raw",
        Mock(side_effect=RedfishException(409, "Alias is not unique", body)),
    )

    with pytest.raises(RedfishException) as error:
        client.set_resource_alias(resource, "primary-system")

    assert error.value.status_code == 409
    assert "PropertyValueConflict" in error.value.body
