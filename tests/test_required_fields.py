"""Required-field policies for Redfish response models."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishMissingAttributeError
from redfish_sdk.http_client import RedfishHttpClient
from redfish_sdk.managers.update_strategies import GenericUpdateStrategy
from redfish_sdk.models.actions import ActionDescriptor
from redfish_sdk.models.chassis import Chassis
from redfish_sdk.models.common import Collection, Link
from redfish_sdk.models.processor import Processor
from redfish_sdk.models.systems import System
from redfish_sdk.models.task import Task


@pytest.mark.parametrize("model_class", [System, Chassis, Task])
def test_empty_core_resource_is_rejected(model_class):
    with pytest.raises(RedfishMissingAttributeError):
        model_class.model_validate({})


@pytest.mark.parametrize("model_class", [System, Chassis])
@pytest.mark.parametrize(
    "identity",
    [
        {"@odata.id": "/redfish/v1/Resources/1"},
        {"Id": "1"},
    ],
)
def test_core_resource_accepts_legacy_identity_and_oem_fields(
    model_class, identity
):
    payload = {**identity, "Oem": {"Vendor": {"LegacyFlag": True}}}

    resource = model_class.model_validate(payload)

    assert resource.model_dump(by_alias=True, exclude_none=True)["Oem"]


def test_task_requires_identity_and_state():
    with pytest.raises(RedfishMissingAttributeError) as missing_identity:
        Task.model_validate({"TaskState": "Running"})
    assert missing_identity.value.attribute == "@odata.id or Id or TaskMonitor"

    with pytest.raises(RedfishMissingAttributeError) as missing_state:
        Task.model_validate({"Id": "7"})
    assert missing_state.value.attribute == "TaskState"

    task = Task.model_validate(
        {"Id": "7", "TaskState": "Running", "Oem": {"VendorState": "Busy"}}
    )
    assert task.id == "7"
    assert task.oem == {"VendorState": "Busy"}


def test_collection_requires_members_property():
    with pytest.raises(RedfishMissingAttributeError) as error:
        Collection[Link].model_validate({"@odata.id": "/redfish/v1/Systems"})

    assert error.value.attribute == "Members"


def test_collection_member_requires_odata_id():
    with pytest.raises(RedfishMissingAttributeError) as error:
        Collection[Link].model_validate({"Members": [{"Id": "1"}]})

    assert error.value.attribute == "Members[0].@odata.id"


def test_expanded_collection_member_requires_usable_identity(monkeypatch):
    client = RedfishClient(
        "bmc.example",
        "user",
        "password",
        verify_ssl=True,
        strict_collection_errors=True,
    )
    monkeypatch.setattr(
        client._http_client,
        "get_raw",
        lambda path: {"Members": [{"@odata.id": "/redfish/v1/Processors/1"}]},
    )
    monkeypatch.setattr(
        client._http_client,
        "get",
        lambda path, model_class: Processor.model_validate({}),
    )

    with pytest.raises(RedfishMissingAttributeError) as error:
        client._get_collection("/redfish/v1/Processors", Processor)

    assert error.value.attribute == "@odata.id or Id"
    assert error.value.resource_uri == "/redfish/v1/Processors/1"
    client.close()


def test_http_boundary_reports_missing_property_and_request_uri():
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({"Name": "Malformed system"}).encode()
    http = RedfishHttpClient(
        "bmc.example", "user", "password", verify_ssl=True
    )

    with pytest.raises(RedfishMissingAttributeError) as error:
        http._parse(response, System, "/redfish/v1/Systems/1")

    assert error.value.attribute == "@odata.id or Id"
    assert error.value.resource_uri == "/redfish/v1/Systems/1"
    assert "/redfish/v1/Systems/1" in str(error.value)


@pytest.mark.parametrize("target", [None, "", "   ", 7])
def test_action_invocation_requires_valid_target(target):
    action = ActionDescriptor.model_validate({"target": target})

    with pytest.raises(RedfishMissingAttributeError) as error:
        action.require_target(
            action_name="#ComputerSystem.Reset",
            resource_uri="/redfish/v1/Systems/1",
        )

    assert error.value.attribute == "target"
    assert error.value.resource_uri == "/redfish/v1/Systems/1"


def test_update_action_does_not_guess_an_unadvertised_target():
    client = MagicMock()
    client._get_update_service.return_value.odata_id = (
        "/redfish/v1/UpdateService"
    )
    client._http_client.get_raw.return_value = {"Actions": {}}

    with pytest.raises(RedfishMissingAttributeError) as error:
        GenericUpdateStrategy().execute(client, "https://example.test/fw.bin")

    assert error.value.attribute == "target"
    assert error.value.resource_uri == "/redfish/v1/UpdateService"
    client._http_client.post.assert_not_called()
