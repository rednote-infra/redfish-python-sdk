"""Capability-driven PolicyService models and CRUD operations."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import (
    RedfishException,
    RedfishNotFoundError,
    RedfishValidationError,
)
from redfish_sdk.models.policy import Policy, PolicyCondition, PolicyResponse
from redfish_sdk.models.root import RootService

RACK_POWER_CAP = {
    "Id": "RackPowerCap",
    "Name": "Rack Power Cap Policy",
    "Predefined": False,
    "Enabled": True,
    "TriggerCondition": {
        "Type": "Sum",
        "CompareValue": "10000",
        "Operator": "GreaterThanOrEqual",
        "SubordinateConditions": [
            {
                "Type": "Read",
                "ResourcePath": "/redfish/v1/Chassis/1/Power",
                "PropertyPath": "/PowerControl/0/PowerConsumedWatts",
            },
            {
                "Type": "Read",
                "ResourcePath": "/redfish/v1/Chassis/Blade1/Sensors/PowerConsumption",
            },
        ],
    },
    "Response": [
        {
            "ResponseAction": "Reset",
            "TargetURI": "/redfish/v1/Systems/1",
            "ResetType": "GracefulShutdown",
        },
        {"ResponseAction": "Recheck", "DelaySeconds": 60},
        {
            "ResponseAction": "Reset",
            "TargetURI": "/redfish/v1/Chassis/Blade1",
            "ResetType": "GracefulShutdown",
        },
    ],
}


def make_response(method, path, status=200, body=None, etag=None):
    result = requests.Response()
    result.request = requests.Request(method, f"https://mock-bmc{path}").prepare()
    result.status_code = status
    result._content = json.dumps(body).encode() if body is not None else b""
    if etag:
        result.headers["ETag"] = etag
    return result


@pytest.fixture
def policy_client(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    root = RootService.model_validate({
        "PolicyService": {"@odata.id": "/custom/policy-service"}
    })
    service = {
        "@odata.id": "/custom/policy-service",
        "Id": "PolicyService",
        "Name": "Policy Service",
        "ResourceTypesSupported": ["ComputerSystem", "Chassis"],
        "ConditionTypesSupported": ["Sum", "Read", "Compare"],
        "ActionsSupported": ["Reset", "Recheck", "Event"],
        "OperatingMode": "Enabled",
        "Policies": {"@odata.id": "/custom/policies"},
    }
    member = {
        **RACK_POWER_CAP,
        "@odata.id": "/custom/policies/rack-cap",
        "@odata.type": "#Policy.v1_0_0.Policy",
    }
    calls = []
    state = {"member": member, "fail_post": False}
    monkeypatch.setattr(client, "_get_root", lambda: root)

    def request(method, path, **arguments):
        calls.append((method, path, arguments))
        if method == "GET" and path == "/custom/policy-service":
            return make_response(method, path, body=service)
        if method == "GET" and path == "/custom/policies":
            return make_response(
                method,
                path,
                body={"Members": [{"@odata.id": "/custom/policies/rack-cap"}]},
            )
        if method == "GET" and path == "/custom/policies/rack-cap":
            return make_response(method, path, body=state["member"], etag='W/"policy-1"')
        if method == "GET" and path == "/redfish/v1/Systems/1":
            return make_response(
                method,
                path,
                body={"@odata.type": "#ComputerSystem.v1_25_0.ComputerSystem"},
            )
        if method == "GET" and path == "/redfish/v1/Chassis/Blade1":
            return make_response(
                method,
                path,
                body={"@odata.type": "#Chassis.v1_29_0.Chassis"},
            )
        if method == "POST" and path == "/custom/policies":
            if state["fail_post"]:
                return make_response(
                    method,
                    path,
                    status=400,
                    body={"error": {"code": "Base.Invalid", "message": "Rejected"}},
                )
            created = {
                **arguments["json"],
                "@odata.id": f"/custom/policies/{arguments['json']['Id']}",
            }
            return make_response(method, path, status=201, body=created, etag='W/"created"')
        if method == "PATCH" and path == "/custom/policies/rack-cap":
            updated = {**state["member"], **arguments["json"]}
            return make_response(method, path, body=updated, etag='W/"policy-2"')
        if method == "DELETE" and path == "/custom/policies/rack-cap":
            return make_response(method, path, status=204)
        pytest.fail(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(client._http_client, "_request", request)
    yield client, calls, state
    client.close()


def test_rack_power_cap_policy_round_trips_nested_conditions_and_responses():
    payload = deepcopy(RACK_POWER_CAP)
    payload["Oem"] = {"Vendor": {"Owner": "datacenter"}}
    payload["TriggerCondition"]["Oem"] = {"Vendor": {"Window": 3}}
    policy = Policy.model_validate(payload)

    assert policy.trigger_condition.subordinate_conditions[1].resource_path.endswith(
        "/PowerConsumption"
    )
    assert [step.response_action for step in policy.response] == [
        "Reset",
        "Recheck",
        "Reset",
    ]
    assert policy.model_dump(by_alias=True, exclude_none=True) == payload


def test_policy_service_list_and_get_follow_custom_advertised_links(policy_client):
    client, _, _ = policy_client

    service = client.get_policy_service()
    policies = client.get_policies()

    assert service.operating_mode == "Enabled"
    assert service.resource_types_supported == ["ComputerSystem", "Chassis"]
    assert policies[0].odata_id == "/custom/policies/rack-cap"
    assert client.get_policy("RackPowerCap") is not None
    assert client.get_policy("/custom/policies/rack-cap").id == "RackPowerCap"
    with pytest.raises(RedfishNotFoundError, match="PolicyService"):
        root = RootService.model_validate({})
        client._get_root = lambda: root
        client.get_policy_service()


def test_create_policy_validates_capabilities_and_preserves_response_order(
    policy_client,
):
    client, calls, _ = policy_client
    policy = client.create_policy(
        "RackPowerCap2",
        "Rack Power Cap Policy 2",
        PolicyCondition.model_validate(RACK_POWER_CAP["TriggerCondition"]),
        [PolicyResponse.model_validate(item) for item in RACK_POWER_CAP["Response"]],
        enabled=True,
        oem={"Vendor": {"Owner": "datacenter"}},
    )

    post = next(call for call in calls if call[:2] == ("POST", "/custom/policies"))
    assert [item["ResponseAction"] for item in post[2]["json"]["Response"]] == [
        "Reset",
        "Recheck",
        "Reset",
    ]
    assert post[2]["json"]["Oem"] == {"Vendor": {"Owner": "datacenter"}}
    assert policy.odata_id == "/custom/policies/RackPowerCap2"


@pytest.mark.parametrize(
    "condition_type,response_action,error",
    [
        ("Average", "Reset", "condition type"),
        ("Sum", "HTTP", "response action"),
    ],
)
def test_create_rejects_unadvertised_condition_and_action_types(
    policy_client, condition_type, response_action, error
):
    client, calls, _ = policy_client
    condition = PolicyCondition.model_validate({
        **RACK_POWER_CAP["TriggerCondition"],
        "Type": condition_type,
    })
    responses = [PolicyResponse(response_action=response_action)]

    with pytest.raises(RedfishValidationError, match=error):
        client.create_policy("Unsupported", "Unsupported", condition, responses)
    assert not any(method == "POST" for method, _, _ in calls)


def test_create_rejects_unadvertised_reset_target_type(policy_client, monkeypatch):
    client, calls, _ = policy_client
    original_request = client._http_client._request

    def request(method, path, **arguments):
        if method == "GET" and path == "/redfish/v1/Managers/1":
            return make_response(
                method,
                path,
                body={"@odata.type": "#Manager.v1_22_0.Manager"},
            )
        return original_request(method, path, **arguments)

    monkeypatch.setattr(client._http_client, "_request", request)
    response = PolicyResponse(
        response_action="Reset",
        target_uri="/redfish/v1/Managers/1",
        reset_type="ForceRestart",
    )

    with pytest.raises(RedfishValidationError, match="resource type"):
        client.create_policy(
            "UnsupportedTarget",
            "Unsupported Target",
            PolicyCondition(type="Compare"),
            [response],
        )
    assert not any(method == "POST" for method, _, _ in calls)


def test_update_enable_disable_and_delete_use_member_etag(policy_client):
    client, calls, _ = policy_client

    client.update_policy(
        "RackPowerCap",
        responses=[PolicyResponse(response_action="Recheck", delay_seconds=30)],
    )
    client.disable_policy("RackPowerCap")
    client.enable_policy("RackPowerCap")
    client.delete_policy("RackPowerCap")

    patches = [call for call in calls if call[0] == "PATCH"]
    assert patches[0][2]["json"] == {
        "Response": [{"DelaySeconds": 30, "ResponseAction": "Recheck"}]
    }
    assert patches[1][2]["json"] == {"Enabled": False}
    assert patches[2][2]["json"] == {"Enabled": True}
    assert all(call[2]["headers"]["If-Match"] == 'W/"policy-1"' for call in patches)
    delete = next(call for call in calls if call[0] == "DELETE")
    assert delete[2]["headers"]["If-Match"] == 'W/"policy-1"'


def test_predefined_policy_allows_toggle_but_rejects_definition_update_and_delete(
    policy_client,
):
    client, calls, state = policy_client
    state["member"] = {**state["member"], "Predefined": True}

    client.disable_policy("RackPowerCap")
    with pytest.raises(RedfishValidationError, match="predefined"):
        client.update_policy(
            "RackPowerCap",
            responses=[PolicyResponse(response_action="Recheck")],
        )
    with pytest.raises(RedfishValidationError, match="predefined"):
        client.delete_policy("RackPowerCap")

    assert len([call for call in calls if call[0] == "PATCH"]) == 1
    assert not any(call[0] == "DELETE" for call in calls)


def test_policy_create_errors_propagate(policy_client):
    client, _, state = policy_client
    state["fail_post"] = True

    with pytest.raises(RedfishException) as error:
        client.create_policy(
            "Rejected",
            "Rejected",
            PolicyCondition(type="Compare"),
            [PolicyResponse(response_action="Recheck")],
        )

    assert error.value.status_code == 400


def test_policy_discovery_has_no_mutating_side_effect(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    monkeypatch.setattr(client, "_get_root", lambda: RootService.model_validate({}))
    mutation = Mock()
    monkeypatch.setattr(client._http_client, "_request", mutation)

    with pytest.raises(RedfishNotFoundError, match="PolicyService"):
        client.get_policy_service()
    mutation.assert_not_called()
    client.close()
