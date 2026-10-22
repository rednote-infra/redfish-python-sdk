"""Event action responses and standard subscription serialization (no BMC)."""

import json
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient, RedfishException
from redfish_sdk.models.event import EventService


@pytest.fixture
def client(monkeypatch):
    with RedfishClient("mock-bmc", "mock-user", "mock-password") as client:
        service = EventService.model_validate({
            "Subscriptions": {"@odata.id": "/redfish/v1/EventService/Subscriptions"},
            "Actions": {"#EventService.SubmitTestEvent": {"target": "/submit"}},
        })
        monkeypatch.setattr(client, "_get_event_service", lambda: service)
        yield client


def response(status, body):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode() if body is not None else b""
    result.request = requests.Request("POST", "https://mock-bmc/submit").prepare()
    return result


def test_submit_preserves_async_task_and_omits_legacy_event_type(client, monkeypatch):
    task = {
        "@odata.id": "/redfish/v1/TaskService/Tasks/7",
        "@odata.type": "#Task.v1_4_2.Task",
        "TaskState": "New",
        "TaskMonitor": "/redfish/v1/TaskService/TaskMonitors/7",
    }
    post = Mock(return_value=response(202, task))
    monkeypatch.setattr(client._http_client._session, "post", post)
    result = client.submit_test_event(message_id="Base.1.12.Success")
    assert result.model_dump(by_alias=True, exclude_none=True) == task
    assert post.call_args.kwargs["json"] == {"MessageId": "Base.1.12.Success"}


def test_submit_preserves_synchronous_response(client, monkeypatch):
    monkeypatch.setattr(client._http_client._session, "post", Mock(return_value=response(204, None)))
    result = client.submit_test_event(message_id="Base.1.12.Success")
    assert result.model_dump(exclude_none=True) == {}


def test_submit_does_not_hide_server_errors(client, monkeypatch):
    body = {"error": {"code": "Base.1.12.ActionParameterMissing"}}
    monkeypatch.setattr(client._http_client._session, "post", Mock(return_value=response(400, body)))
    with pytest.raises(RedfishException) as error:
        client.submit_test_event(message_id="Base.1.12.Success")
    assert error.value.status_code == 400
    assert json.loads(error.value.body) == body


def test_header_dict_is_normalized_without_changing_input(client, monkeypatch):
    headers = {"X-Test": "value"}
    post = Mock(return_value=response(201, {"Id": "1"}))
    monkeypatch.setattr(client._http_client._session, "post", post)
    client.subscribe("https://receiver/events", context="test", http_headers=headers)
    body = post.call_args.kwargs["json"]
    assert body["HttpHeaders"] == [headers]
    assert "EventTypes" not in body
    assert headers == {"X-Test": "value"}


def test_raw_body_preserves_vendor_header_shape(client, monkeypatch):
    body = {"Destination": "https://receiver/events", "HttpHeaders": {"X-Test": "value"}}
    post = Mock(return_value=response(201, {"Id": "1"}))
    monkeypatch.setattr(client._http_client._session, "post", post)
    client.subscribe("unused", raw_body=body)
    assert post.call_args.kwargs["json"] == body
