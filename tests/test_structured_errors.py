"""Structured HTTP failures and password recovery, without a live BMC."""
import json
from unittest.mock import Mock

import pytest
import requests

import redfish_sdk as sdk
from redfish_sdk.exceptions import RedfishAuthError, RedfishException, RedfishNotFoundError
from redfish_sdk.http_client import RedfishHttpClient
from redfish_sdk.models.common import ExtendedInfo, Link, RedfishError
from redfish_sdk.models.root import RootLinks, RootService

PATH = "/redfish/v1/Systems/Example"
ACCOUNT = "/redfish/v1/AccountService/Accounts/Example"
SESSIONS = "/redfish/v1/SessionService/Sessions"


def response(status=400, payload=None, headers=None, body=None):
    result = requests.Response()
    result.status_code = status
    result._content = body if body is not None else json.dumps(payload or {}).encode()
    result.headers.update(headers or {})
    result.request = requests.Request("GET", f"https://example.test{PATH}").prepare()
    return result


@pytest.fixture
def http():
    client = RedfishHttpClient("example.test", "test-user", "test-password", verify_ssl=True)
    yield client
    client._session.delete = Mock(return_value=response(204))
    client.close()


def test_standard_error_retains_all_details(http):
    payload = {"error": {"code": "Base.1.0.GeneralError", "message": "  Invalid request.  ",
        "@Message.ExtendedInfo": [
            {"MessageId": "Base.1.0.PropertyValueNotInList", "Message": "Choose a supported mode.",
             "MessageArgs": ["Example", "Mode"], "MessageSeverity": "Warning",
             "Resolution": "Select another mode.", "RelatedProperties": ["#/Mode"],
             "VendorCode": "EXAMPLE-1", "Oem": {"Example": {"Detail": 7}}},
            {"MessageId": "Base.1.0.PropertyMissing", "Message": "Name is required.",
             "Severity": "Critical", "RelatedProperties": ["#/Name"]},
        ]}}
    result = response(payload=payload, headers={"Retry-After": "12", "X-Request-ID": "example-trace"})
    with pytest.raises(RedfishException) as caught:
        http._raise_for_status(result, PATH)
    error = caught.value
    assert error.status_code == 400 and error.code == "Base.1.0.GeneralError"
    assert error.message == "  Invalid request.  "
    assert error.body == result.text
    assert error.error.code == error.code
    assert len(error.extended_info) == 2 and isinstance(error.extended_info[0], ExtendedInfo)
    assert error.extended_info[0].message_args == ["Example", "Mode"]
    assert error.extended_info[0].vendor_code == "EXAMPLE-1"
    assert error.extended_info[0].oem["Example"]["Detail"] == 7
    assert error.extended_info[0].resolution == "Select another mode."
    assert error.related_properties == ["#/Mode", "#/Name"]
    assert error.retry_after == "12" and error.request_id == "example-trace"
    assert error.method == "GET" and error.path == PATH
    assert error.severity == "Warning" and error.resolution == "Select another mode."
    assert "Base.1.0.GeneralError" in str(error)


@pytest.mark.parametrize(("status", "name"), [
    (400, "RedfishBadRequestError"), (401, "RedfishAuthError"), (403, "RedfishAuthError"),
    (404, "RedfishNotFoundError"), (409, "RedfishConflictError"),
    (412, "RedfishPreconditionFailedError"), (429, "RedfishRateLimitError"),
    (503, "RedfishServiceUnavailableError"),
])
def test_typed_failures_keep_message_and_base_contract(http, status, name):
    with pytest.raises(RedfishException) as caught:
        http._raise_for_status(response(status, {"error": {"message": "Original message"}}), PATH)
    assert isinstance(caught.value, getattr(sdk, name))
    assert caught.value.message == "Original message"
    assert caught.value.status_code == status


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'{"error":42}',
    b'{"error":{"code":123,"@Message.ExtendedInfo":[null,42]}}'])
def test_malformed_failure_never_masks_http_status(http, body):
    with pytest.raises(RedfishNotFoundError) as caught:
        http._raise_for_status(response(404, body=body), PATH)
    assert caught.value.status_code == 404 and caught.value.body == body.decode()
    assert caught.value.message


def test_extended_message_used_only_without_usable_top_message(http):
    with pytest.raises(RedfishException) as caught:
        http._raise_for_status(response(payload={"error": {"message": "  ",
            "@Message.ExtendedInfo": [{"Message": "Exact extended message"}]}}), PATH)
    assert caught.value.message == "Exact extended message"


def test_sensitive_details_are_available_but_not_displayed(http, caplog):
    message = "Password test-password rejected; Authorization: Basic c2VjcmV0"
    result = response(payload={"error": {"code": "Example.Invalid", "message": message,
        "Password": "test-password", "@Message.ExtendedInfo": [{"Message": message}]}},
        headers={"X-Auth-Token": "secret-token"})
    with pytest.raises(RedfishException) as caught:
        http._raise_for_status(result, PATH)
    assert caught.value.message == message
    assert caught.value.body == result.text
    display = str(caught.value) + repr(caught.value) + caplog.text
    assert "test-password" not in display and "c2VjcmV0" not in display
    assert "secret-token" not in display


@pytest.mark.parametrize("version", ["1.0", "1.19"])
@pytest.mark.parametrize("nested", [True, False])
def test_password_change_required(http, version, nested):
    code = f"Base.{version}.PasswordChangeRequired"
    info = {"MessageId": code, "MessageArgs": [ACCOUNT]}
    payload = {"error": {"code": "Base.1.0.GeneralError", "@Message.ExtendedInfo": [info]}}
    if not nested:
        payload = {"error": {"code": code}}
    with pytest.raises(RedfishAuthError) as caught:
        http._raise_for_status(response(403, payload), PATH)
    assert isinstance(caught.value, sdk.RedfishPasswordChangeRequiredError)
    assert caught.value.account_uri == (ACCOUNT if nested else None)


@pytest.mark.parametrize("info", [
    {"MessageId": "Example.1.0.PasswordChangeRequired"},
    {"MessageId": "Base.bad.PasswordChangeRequired"},
    {"MessageId": 12, "MessageArgs": "not-an-array"},
])
def test_malformed_or_oem_message_does_not_trigger_password_recovery(http, info):
    with pytest.raises(RedfishAuthError) as caught:
        http._raise_for_status(response(403, {"error": {"@Message.ExtendedInfo": [info]}}), PATH)
    assert not isinstance(caught.value, sdk.RedfishPasswordChangeRequiredError)


def restricted_response():
    return response(201, {"@Message.ExtendedInfo": [{
        "MessageId": "Base.1.18.PasswordChangeRequired", "MessageArgs": [ACCOUNT],
    }]}, {"X-Auth-Token": "restricted-token", "Location": f"{SESSIONS}/Example"})


@pytest.mark.parametrize("switch_to_token_auth", [False, True])
@pytest.mark.parametrize("malformed_message", [False, True])
def test_explicit_restricted_session_retained_for_recovery(monkeypatch, switch_to_token_auth, malformed_message):
    client = sdk.RedfishClient("example.test", "test-user", "test-password", verify_ssl=True)
    root = RootService.model_construct(links=RootLinks.model_construct(
        sessions=Link.model_construct(odata_id=SESSIONS)))
    monkeypatch.setattr(client, "_get_root", lambda: root)
    result = restricted_response()
    if malformed_message:
        payload = result.json()
        payload["@Message.ExtendedInfo"][0]["Message"] = {"invalid": "object"}
        result._content = json.dumps(payload).encode()
    monkeypatch.setattr(client._http_client._session, "post", Mock(return_value=result))
    delete = Mock(return_value=response(204))
    monkeypatch.setattr(client._http_client._session, "delete", delete)
    try:
        with pytest.raises(sdk.RedfishPasswordChangeRequiredError) as caught:
            client.create_session("test-user", "test-password", switch_to_token_auth=switch_to_token_auth)
        assert caught.value.account_uri == ACCOUNT
        assert client._http_client._session_key == "restricted-token"
    finally:
        client.close()
    assert delete.call_count == 1


def test_lazy_login_cleanup_in_context_manager(monkeypatch):
    client = sdk.RedfishClient("example.test", "test-user", "test-password",
                               verify_ssl=True, auth_mode=sdk.AuthenticationMode.SESSION)
    monkeypatch.setattr(client._http_client._external_session, "post", Mock(return_value=restricted_response()))
    delete = Mock(return_value=response(204))
    monkeypatch.setattr(client._http_client._session, "delete", delete)
    with pytest.raises(sdk.RedfishPasswordChangeRequiredError), client:
        client.get_raw(PATH)
    assert delete.call_count == 1
    assert client._http_client._session_key is None


def test_password_required_401_does_not_attempt_refresh(http, monkeypatch):
    http.set_auth_token("existing-token")
    monkeypatch.setattr(http._session, "get", Mock(return_value=response(401, {
        "error": {"code": "Base.1.0.PasswordChangeRequired"},
    })))
    login = Mock()
    monkeypatch.setattr(http._external_session, "post", login)
    with pytest.raises(sdk.RedfishPasswordChangeRequiredError):
        http.get_raw(PATH)
    login.assert_not_called()


def test_legacy_exception_constructors():
    assert str(RedfishException(500, "legacy", "body")) == "[HTTP 500] legacy"
    assert RedfishAuthError().status_code == 401
    assert RedfishNotFoundError("/missing").message == "Resource not found: /missing"
    info = ExtendedInfo(message="Existing caller model")
    assert RedfishError(extended_info=[info]).extended_info[0] is info


def test_oem_details_and_http_date_retry_after(http):
    date = "Wed, 11 Nov 2026 10:00:00 GMT"
    with pytest.raises(sdk.RedfishServiceUnavailableError) as caught:
        http._raise_for_status(response(503, {"error": {"code": "Example.1.0.Busy",
            "message": "Wait for maintenance.", "Oem": {"Example": {"RetryHint": "Later"}}}},
            {"Retry-After": date}), PATH)
    assert caught.value.retry_after == date
    assert caught.value.error.model_extra["Oem"]["Example"]["RetryHint"] == "Later"


def test_password_change_message_without_account_uri(http):
    with pytest.raises(sdk.RedfishPasswordChangeRequiredError) as caught:
        http._raise_for_status(response(403, {"error": {"@Message.ExtendedInfo": [{
            "MessageId": "Base.1.18.PasswordChangeRequired", "MessageArgs": [],
        }]}}), PATH)
    assert caught.value.account_uri is None


def test_lazy_restricted_session_retained_for_explicit_cleanup(http, monkeypatch):
    monkeypatch.setattr(http._external_session, "post", Mock(return_value=restricted_response()))
    with pytest.raises(sdk.RedfishPasswordChangeRequiredError):
        http._refresh_session(None)
    assert http._session_key == "restricted-token"
    assert http.session_location == f"{SESSIONS}/Example"


def test_password_message_with_malformed_optional_details(http):
    with pytest.raises(sdk.RedfishPasswordChangeRequiredError) as caught:
        http._raise_for_status(response(403, {"error": {"message": "Exact downstream message",
            "@Message.ExtendedInfo": [{"MessageId": "Base.1.18.PasswordChangeRequired",
                "Message": {"invalid": "object"}, "MessageArgs": "invalid"}]}}), PATH)
    assert caught.value.message == "Exact downstream message"
    assert caught.value.account_uri is None


@pytest.mark.parametrize("password", ['quote"secret', r"back\slash", "line\nbreak", "unicode-密钥"])
def test_escaped_password_is_redacted_before_error_log_serialization(http, caplog, password):
    http._password = password
    result = response(payload={"error": {"message": f"Rejected credential: {password}"}})
    with pytest.raises(RedfishException) as caught:
        http._raise_for_status(result, PATH)
    record = next(r for r in caplog.records if r.msg.startswith("Request failed:"))
    logged_body = json.loads(record.args[-1])
    assert password not in logged_body["error"]["message"]
    assert "<redacted>" in logged_body["error"]["message"]
    assert caught.value.body == result.text
    assert caught.value.message == f"Rejected credential: {password}"


def test_explicit_login_uses_attempted_password_and_returned_token_for_display(monkeypatch):
    attempted = 'new-credential"with\\escapes'
    token = "newly-issued-restricted-token"
    message = f"Change password {attempted}; session {token} is restricted."
    client = sdk.RedfishClient("example.test", "old-user", "old-password", verify_ssl=True)
    root = RootService.model_construct(links=RootLinks.model_construct(
        sessions=Link.model_construct(odata_id=SESSIONS)))
    monkeypatch.setattr(client, "_get_root", lambda: root)
    result = response(201, {"@Message.ExtendedInfo": [{
        "MessageId": "Base.1.18.PasswordChangeRequired", "Message": message, "MessageArgs": [ACCOUNT],
    }]}, {"X-Auth-Token": token, "Location": f"{SESSIONS}/Example"})
    monkeypatch.setattr(client._http_client._session, "post", Mock(return_value=result))
    monkeypatch.setattr(client._http_client._session, "delete", Mock(return_value=response(204)))
    with client, pytest.raises(sdk.RedfishPasswordChangeRequiredError) as caught:
        client.create_session("new-user", attempted, switch_to_token_auth=True)
    error = caught.value
    for display in (str(error), repr(error), str(error.args)):
        assert attempted not in display and repr(attempted)[1:-1] not in display
        assert token not in display
    assert error.message == message and error.body == result.text


class BrokenBodyResponse(requests.Response):
    def __init__(self, status, failure):
        super().__init__()
        self.status_code = status
        self.failure = failure
        self.request = requests.Request("GET", f"https://example.test{PATH}").prepare()

    @property
    def text(self):
        raise self.failure("Error body could not be read")


@pytest.mark.parametrize("failure", [requests.exceptions.ChunkedEncodingError, requests.exceptions.ContentDecodingError])
@pytest.mark.parametrize("status", [401, 404, 500])
def test_unreadable_body_preserves_http_failure(http, failure, status):
    with pytest.raises(RedfishException) as caught:
        http._raise_for_status(BrokenBodyResponse(status, failure), PATH)
    assert caught.value.status_code == status
    assert caught.value.body == "" and caught.value.message


def test_unreadable_401_body_still_allows_session_refresh(http, monkeypatch):
    http.set_auth_token("expired-token")
    monkeypatch.setattr(http._session, "get", Mock(side_effect=[
        BrokenBodyResponse(401, requests.exceptions.ChunkedEncodingError), response(200, {"ok": True}),
    ]))
    login = Mock(return_value=response(201, headers={
        "X-Auth-Token": "refreshed-token", "Location": f"{SESSIONS}/Example",
    }))
    monkeypatch.setattr(http._external_session, "post", login)
    assert http.get_raw(PATH) == {"ok": True}
    assert login.call_count == 1
