"""Complete generic HTTP controls without a live Redfish service."""
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from redfish_sdk import GenericResponse, RedfishClient, RedfishValidationError, RetryPolicy

PATH = "/redfish/v1/Systems/Example"
ORIGIN = "https://example.test"


def response(status=200, content=b'{"ok":true}', headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = content
    result.encoding = "utf-8"
    result.headers.update(headers or {})
    result.url = ORIGIN + PATH
    result.request = requests.Request("GET", result.url).prepare()
    return result


@pytest.fixture
def client():
    with RedfishClient("example.test", "test-user", "test-password", verify_ssl=True) as client:
        yield client


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
def test_all_verbs_and_request_options(client, monkeypatch, method):
    send = Mock(return_value=response(content=b"" if method == "HEAD" else b'{"ok":true}',
        headers={"ETag": '"current"', "X-Trace": "example"}))
    monkeypatch.setattr(client._http_client._session, method.lower(), send)
    params = [("$select", "Id,Name"), ("$filter", "Name eq 'A&B'"), ("tag", "a"), ("tag", "b")]
    options = {} if method in ("GET", "HEAD") else {"body": {"Enabled": False}}
    result = client.request(method, PATH, params=params, headers={"If-Match": '"explicit"'},
                            connect_timeout=2, read_timeout=120, **options)
    assert isinstance(result, GenericResponse)
    assert result.headers["etag"] == '"current"'
    assert result.headers["x-trace"] == "example"
    kwargs = send.call_args.kwargs
    assert kwargs["params"] == params
    assert kwargs["headers"]["If-Match"] == '"explicit"'
    assert kwargs["timeout"] == (2, 120) and kwargs["allow_redirects"] is False
    prepared = requests.Request(method, send.call_args.args[0], params=kwargs["params"]).prepare()
    decoded = parse_qs(urlsplit(prepared.url).query)
    assert decoded["$filter"] == ["Name eq 'A&B'"] and decoded["tag"] == ["a", "b"]
    if options:
        assert kwargs["json"] == {"Enabled": False}
    else:
        assert "json" not in kwargs and "data" not in kwargs
    send.assert_called_once()


@pytest.mark.parametrize("header", ["Authorization", "authorization", "X-Auth-Token", "x-auth-token"])
def test_managed_auth_cannot_be_replaced(client, monkeypatch, header):
    send = Mock()
    monkeypatch.setattr(client._http_client._session, "get", send)
    with pytest.raises(RedfishValidationError):
        client.request("GET", PATH, headers={header: "replacement"})
    send.assert_not_called()


@pytest.mark.parametrize("bad_timeout", [0, -1, True, float("inf"), float("nan"), "slow"])
def test_invalid_timeout_rejected_before_request(client, monkeypatch, bad_timeout):
    send = Mock()
    monkeypatch.setattr(client._http_client._session, "get", send)
    with pytest.raises(RedfishValidationError):
        client.request("GET", PATH, read_timeout=bad_timeout)
    send.assert_not_called()


def test_timeout_overrides_do_not_modify_client_defaults(client, monkeypatch):
    send = Mock(return_value=response())
    monkeypatch.setattr(client._http_client._session, "get", send)
    client.request("GET", PATH, read_timeout=80)
    assert send.call_args.kwargs["timeout"] == (10, 80)
    client.request("GET", PATH)
    assert send.call_args.kwargs["timeout"] == (10, 30)


@pytest.mark.parametrize("status", [301, 302, 303, 304, 307, 308])
def test_redirects_are_metadata_by_default(client, monkeypatch, status):
    send = Mock(return_value=response(status, b"", {"Location": "/new-target"}))
    monkeypatch.setattr(client._http_client._session, "get", send)
    result = client.request("GET", PATH)
    assert result.status_code == status and result.location == "/new-target"
    send.assert_called_once()


def test_explicit_same_origin_redirect_drops_old_query_parameters(client, monkeypatch):
    send = Mock(side_effect=[response(307, b"", {"Location": "/new-target?page=2"}), response()])
    monkeypatch.setattr(client._http_client._session, "get", send)
    assert client.request("GET", PATH, params={"$top": 5}, allow_redirects=True)["ok"] is True
    assert send.call_args_list[0].kwargs["params"] == {"$top": 5}
    assert send.call_args_list[1].args[0] == ORIGIN + "/new-target?page=2"
    assert send.call_args_list[1].kwargs.get("params") is None


@pytest.mark.parametrize("target", ["https://other.example/resource", "http://example.test/resource"])
def test_cross_origin_or_downgrade_redirect_rejected_before_following(client, monkeypatch, target):
    send = Mock(return_value=response(307, b"", {"Location": target}))
    monkeypatch.setattr(client._http_client._session, "post", send)
    with pytest.raises(RedfishValidationError):
        client.request("POST", PATH, body={"Password": "synthetic"}, allow_redirects=True)
    send.assert_called_once()


def test_307_preserves_delete_body(client, monkeypatch):
    send = Mock(side_effect=[response(307, b"", {"Location": "/new-target"}), response(204, b"")])
    monkeypatch.setattr(client._http_client._session, "delete", send)
    client.request("DELETE", PATH, body={"Mode": "Graceful"}, allow_redirects=True)
    assert all(call.kwargs["json"] == {"Mode": "Graceful"} for call in send.call_args_list)


def test_303_switches_post_to_get_without_body(client, monkeypatch):
    post = Mock(return_value=response(303, b"", {"Location": "/result"}))
    get = Mock(return_value=response())
    monkeypatch.setattr(client._http_client._session, "post", post)
    monkeypatch.setattr(client._http_client._session, "get", get)
    client.request("POST", PATH, body={"Input": 1}, allow_redirects=True)
    assert "json" not in get.call_args.kwargs and "data" not in get.call_args.kwargs
    assert get.call_args.args[0] == ORIGIN + "/result"


def test_explicit_json_null_is_distinct_from_omitted_body(client, monkeypatch):
    send = Mock(return_value=response())
    monkeypatch.setattr(client._http_client._session, "delete", send)
    client.request("DELETE", PATH, body=None)
    assert send.call_args.kwargs["data"] == "null"
    client.request("DELETE", PATH)
    assert "data" not in send.call_args.kwargs and "json" not in send.call_args.kwargs


def test_generic_put_does_not_retry_by_default(client, monkeypatch):
    from redfish_sdk import RedfishException
    client._http_client.retry_5xx = 1
    client._http_client.retry_backoff = 0
    send = Mock(side_effect=[response(503, b'{"error":{"message":"Try later"}}'), response()])
    monkeypatch.setattr(client._http_client._session, "put", send)
    with pytest.raises(RedfishException) as caught:
        client.request("PUT", PATH, body={})
    assert caught.value.message == "Try later"
    send.assert_called_once()
    send.reset_mock(side_effect=True)
    send.side_effect = [response(503, b""), response()]
    assert client.request("PUT", PATH, body={}, retry_policy=RetryPolicy.IDEMPOTENT)["ok"] is True
    assert send.call_count == 2


@pytest.mark.parametrize("content", [b"not-json", b"\x00\xffbinary", b"[1,2]", b"null"])
def test_arbitrary_response_content_remains_available(client, monkeypatch, content):
    monkeypatch.setattr(client._http_client._session, "get", Mock(return_value=response(content=content)))
    assert client.request("GET", PATH).content == content


@pytest.mark.parametrize("method", ["TRACE", "CONNECT", "invalid", 1])
def test_unsupported_methods_fail_before_transport(client, method):
    with pytest.raises(RedfishValidationError):
        client.request(method, PATH)


def test_unstructured_query_string_is_rejected(client):
    with pytest.raises(RedfishValidationError):
        client.request("GET", PATH, params="$top=5")


class CaptureAdapter(requests.adapters.BaseAdapter):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        result = next(self.responses)
        result.request = request
        result.url = request.url
        return result

    def close(self):
        pass


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
def test_prepared_requests_encode_options_on_the_wire(client, method):
    from redfish_sdk import HttpMethod
    adapter = CaptureAdapter([response(204, b"")])
    client._http_client._session.mount(ORIGIN, adapter)
    options = {} if method in ("GET", "HEAD") else {"body": {"Example": False}}
    client.request(HttpMethod(method), PATH, params={"$expand": ".($levels=1)", "tags": ["a&b", "c"]},
                   headers={"X-Vendor-Mode": "Example"}, **options)
    prepared = adapter.requests[0]
    assert prepared.method == method
    assert parse_qs(urlsplit(prepared.url).query)["tags"] == ["a&b", "c"]
    assert prepared.headers["X-Vendor-Mode"] == "Example"
    assert prepared.headers["Authorization"].startswith("Basic ")
    if options:
        assert prepared.body == b'{"Example": false}'


def test_redirect_prepared_request_has_no_stale_body_headers(client):
    adapter = CaptureAdapter([response(303, b"", {"Location": "/result"}), response()])
    client._http_client._session.mount(ORIGIN, adapter)
    headers = {"Content-Type": "application/vnd.example+json"}
    client.request("POST", PATH, headers=headers, body={"Input": 1}, allow_redirects=True)
    redirected = adapter.requests[1]
    assert redirected.method == "GET" and redirected.body is None
    assert "Content-Length" not in redirected.headers and "Content-Type" not in redirected.headers
    assert headers == {"Content-Type": "application/vnd.example+json"}


def test_redirect_loop_has_a_bounded_limit(client, monkeypatch):
    client._http_client._session.max_redirects = 2
    send = Mock(return_value=response(307, b"", {"Location": PATH}))
    monkeypatch.setattr(client._http_client._session, "get", send)
    with pytest.raises(RedfishValidationError, match="redirect limit"):
        client.request("GET", PATH, allow_redirects=True)
    assert send.call_count == 3


def test_conditional_generic_get_does_not_poison_legacy_etag_cache(client, monkeypatch):
    monkeypatch.setattr(client._http_client._session, "get", Mock(return_value=response(headers={"ETag": '"filtered"'})))
    client.request("GET", PATH, params={"$select": "Id"})
    assert PATH not in client._http_client._last_etag


def test_cross_origin_and_bad_auth_headers_fail_before_lazy_login(monkeypatch):
    from redfish_sdk import AuthenticationMode
    with RedfishClient("example.test", "test", "test", verify_ssl=True, auth_mode=AuthenticationMode.SESSION) as client:
        login = Mock()
        monkeypatch.setattr(client._http_client._external_session, "post", login)
        with pytest.raises(RedfishValidationError):
            client.request("GET", "https://other.example/resource")
        with pytest.raises(RedfishValidationError):
            client.request("GET", PATH, headers={"X-Auth-Token": "bad"})
        login.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_read_bodies_are_rejected(client, method):
    with pytest.raises(RedfishValidationError):
        client.request(method, PATH, body={})


def test_invalid_retry_policy_is_rejected_before_lazy_login(monkeypatch):
    from redfish_sdk import AuthenticationMode
    with RedfishClient("example.test", "test", "test", verify_ssl=True, auth_mode=AuthenticationMode.SESSION) as client:
        login = Mock()
        monkeypatch.setattr(client._http_client._external_session, "post", login)
        with pytest.raises(RedfishValidationError):
            client.request("GET", PATH, retry_policy="idempotent")
        login.assert_not_called()


def test_query_sequence_subclasses_are_supported(client, monkeypatch):
    from collections import UserList
    send = Mock(return_value=response())
    monkeypatch.setattr(client._http_client._session, "get", send)
    params = UserList([("$top", 5)])
    client.request("GET", PATH, params=params)
    assert send.call_args.kwargs["params"] == params


def test_session_refresh_preserves_per_request_options(client, monkeypatch):
    client._http_client.set_auth_token("old-token")
    send = Mock(side_effect=[response(401, b""), response()])
    monkeypatch.setattr(client._http_client._session, "get", send)
    monkeypatch.setattr(client._http_client._session, "delete", Mock(return_value=response(204, b"")))
    login = Mock(return_value=response(201, b"", {
        "X-Auth-Token": "new-token", "Location": "/redfish/v1/SessionService/Sessions/Example",
    }))
    monkeypatch.setattr(client._http_client._external_session, "post", login)
    client.request("GET", PATH, params={"$top": 1}, read_timeout=90, headers={"X-Example": "value"})
    assert send.call_count == 2 and login.call_count == 1
    for call in send.call_args_list:
        assert call.kwargs["params"] == {"$top": 1}
        assert call.kwargs["timeout"] == (10, 90)
        assert call.kwargs["headers"]["X-Example"] == "value"
