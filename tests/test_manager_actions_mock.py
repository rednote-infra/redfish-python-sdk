"""Manager reset and log clearing use advertised actions and resource links."""

from unittest.mock import Mock, call

import pytest

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import (
    RedfishException,
    RedfishNotFoundError,
    RedfishValidationError,
)
from redfish_sdk.models.common import RedfishResponse
from redfish_sdk.models.logs import Log
from redfish_sdk.models.managers import Manager, ManagerActions


@pytest.fixture
def manager_client(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    manager = Manager.model_validate({
        "Id": "Self", "@odata.id": "/redfish/v1/Managers/Self",
        "LogServices": {"@odata.id": "/custom/services"},
        "Actions": {"#Manager.Reset": {"target": "/custom/restart", "ResetType@Redfish.AllowableValues": ["ForceRestart"]}},
    })
    services = {
        f"/custom/log/{identifier}": {"Id": identifier, "@odata.id": f"/custom/log/{identifier}", "Actions": {"#LogService.ClearLog": {"target": f"/custom/clear/{identifier}"}}}
        for identifier in ["AuditLog", "SEL", "EventLog"]
    }
    monkeypatch.setattr(client._managers, "get", lambda manager_id=None: manager)
    monkeypatch.setattr(client._http_client, "get_raw", lambda path: {"Members": [{"@odata.id": member} for member in services]} if path == "/custom/services" else pytest.fail(path))
    monkeypatch.setattr(client._http_client, "get", lambda path, model: model.model_validate(services[path]))
    post = Mock(return_value=RedfishResponse())
    monkeypatch.setattr(client._http_client, "post", post)
    yield client, manager, services, post
    client.close()


def test_manager_reset_uses_advertised_target(manager_client):
    client, _, _, post = manager_client
    assert isinstance(client.reset_manager(), RedfishResponse)
    assert post.call_args.args == ("/custom/restart", RedfishResponse)
    assert post.call_args.kwargs["body"].model_dump(by_alias=True) == {"ResetType": "ForceRestart"}


def test_manager_reset_rejects_unsupported_types(manager_client):
    client, _, _, post = manager_client
    with pytest.raises(RedfishValidationError, match="ResetType"):
        client.reset_manager("GracefulRestart")
    post.assert_not_called()


@pytest.mark.parametrize("actions", [None, {}, {"#Manager.Reset": {}}, {"#Manager.Reset": {"target": 7}}])
def test_missing_manager_reset_action(manager_client, actions):
    client, manager, _, post = manager_client
    manager.actions = actions
    with pytest.raises(RedfishValidationError, match="Manager.Reset"):
        client.reset_manager()
    post.assert_not_called()


def test_manager_reset_action_info_validation(manager_client, monkeypatch):
    client, manager, _, post = manager_client
    manager.actions = {"#Manager.Reset": {"target": "/custom/restart", "@Redfish.ActionInfo": "/custom/reset-info"}}
    original_get = client._http_client.get
    monkeypatch.setattr(client._http_client, "get", lambda path, model: model.model_validate({"Parameters": [{"Name": "ResetType", "AllowableValues": ["GracefulRestart"]}]}) if path == "/custom/reset-info" else original_get(path, model))
    with pytest.raises(RedfishValidationError):
        client.reset_manager()
    client.reset_manager("GracefulRestart")
    assert post.call_args.kwargs["body"].model_dump(by_alias=True) == {"ResetType": "GracefulRestart"}


@pytest.mark.parametrize("identifier", ["AuditLog", "SEL", "EventLog"])
def test_manager_log_lookup_and_clear(manager_client, identifier):
    client, _, _, post = manager_client
    log = client.get_manager_log_service(identifier)
    assert log.odata_id == f"/custom/log/{identifier}"
    assert client.get_manager_log_service(log.odata_id).id == identifier
    client.clear_manager_log(identifier)
    post.assert_called_once_with(f"/custom/clear/{identifier}", RedfishResponse, raw_body={})


def test_manager_log_clear_retries_without_body_after_http_400(manager_client):
    client, _, _, post = manager_client
    post.side_effect = [
        RedfishException(400, "JSON body rejected"),
        RedfishResponse(),
    ]

    client.clear_manager_log("SEL")

    assert post.call_args_list == [
        call("/custom/clear/SEL", RedfishResponse, raw_body={}),
        call("/custom/clear/SEL", RedfishResponse),
    ]


def test_missing_clear_action_does_not_mutate(manager_client):
    client, _, services, post = manager_client
    services["/custom/log/SEL"]["Actions"] = {}
    with pytest.raises(RedfishValidationError, match="ClearLog"):
        client.clear_manager_log("SEL")
    post.assert_not_called()


def test_ambiguous_or_missing_manager_log(manager_client):
    client, _, _, post = manager_client
    with pytest.raises(RedfishValidationError, match="Multiple"):
        client.get_manager_log_service()
    with pytest.raises(RedfishNotFoundError):
        client.clear_manager_log("missing")
    post.assert_not_called()


def test_sole_manager_log_can_be_selected_automatically(manager_client):
    client, _, services, post = manager_client
    services.pop("/custom/log/AuditLog")
    services.pop("/custom/log/EventLog")
    client.clear_manager_log()
    post.assert_called_once_with("/custom/clear/SEL", RedfishResponse, raw_body={})


def test_manager_actions_are_typed_and_preserve_oem_data():
    manager = Manager.model_validate({"Actions": {
        "#Manager.Reset": {"target": "/custom/reset", "ResetType@Redfish.AllowableValues": ["ForceRestart"], "@Redfish.ActionInfo": "/custom/info"},
        "#Manager.GeneralDownload": {"target": "/custom/download"},
        "Oem": {"Vendor": {"Enabled": True}},
    }})
    assert isinstance(manager.actions, ManagerActions)
    assert manager.actions.manager_reset.target == "/custom/reset"
    assert manager.actions.manager_reset.action_info == "/custom/info"
    assert manager.actions.manager_reset.reset_type_allowable_values == ["ForceRestart"]
    assert manager.actions.get("#Manager.GeneralDownload")["target"] == "/custom/download"
    assert manager.model_dump(by_alias=True, exclude_none=True)["Actions"]["Oem"]["Vendor"]["Enabled"] is True


def test_log_actions_are_typed_and_keep_collection_actions():
    log = Log.model_validate({"Actions": {
        "#LogService.ClearLog": {"target": "/custom/clear"},
        "#LogService.CollectDiagnosticData": {"target": "/custom/collect"},
    }})
    assert log.actions.clear_log.target == "/custom/clear"
    assert log.actions.get("#LogService.CollectDiagnosticData")["target"] == "/custom/collect"


@pytest.mark.parametrize("values", [[], ["GracefulRestart"]])
def test_manager_reset_rejects_values_excluded_by_action_info(manager_client, monkeypatch, values):
    client, manager, _, post = manager_client
    manager.actions = {"#Manager.Reset": {"target": "/custom/reset", "@Redfish.ActionInfo": "/custom/info"}}
    monkeypatch.setattr(client._http_client, "get", lambda path, model: model.model_validate({"Parameters": [{"Name": "ResetType", "AllowableValues": values}]}))
    with pytest.raises(RedfishValidationError, match="ResetType"):
        client.reset_manager()
    post.assert_not_called()
