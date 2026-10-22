"""Standard header serialization for the existing subscription API; no BMC."""

import json
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.models.event import EventService


@pytest.fixture
def client(monkeypatch):
    with RedfishClient("mock-bmc", "mock-user", "mock-password") as client:
        service = EventService.model_validate({
            "Subscriptions": {"@odata.id": "/redfish/v1/EventService/Subscriptions"},
        })
        monkeypatch.setattr(client, "_get_event_service", lambda: service)
        yield client


def response():
    result = requests.Response()
    result.status_code = 201
    result._content = json.dumps({"Id": "1"}).encode()
    return result


def test_header_dict_is_normalized_without_changing_input(client, monkeypatch):
    headers = {"X-Test": "value"}
    post = Mock(return_value=response())
    monkeypatch.setattr(client._http_client._session, "post", post)
    client.subscribe("https://receiver/events", http_headers=headers)
    assert post.call_args.kwargs["json"]["HttpHeaders"] == [headers]
    assert headers == {"X-Test": "value"}


def test_standard_header_array_is_preserved(client, monkeypatch):
    headers = [{"X-Test": "value"}]
    post = Mock(return_value=response())
    monkeypatch.setattr(client._http_client._session, "post", post)
    client.subscribe("https://receiver/events", http_headers=headers)
    assert post.call_args.kwargs["json"]["HttpHeaders"] == headers


def test_raw_body_preserves_vendor_header_shape(client, monkeypatch):
    body = {"Destination": "https://receiver/events", "HttpHeaders": {"X-Test": "value"}}
    post = Mock(return_value=response())
    monkeypatch.setattr(client._http_client._session, "post", post)
    client.subscribe("unused", raw_body=body)
    assert post.call_args.kwargs["json"] == body
