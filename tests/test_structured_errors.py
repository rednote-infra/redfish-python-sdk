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
    monkeypatch.setattr(client._http_client, "post_raw", lambda *a, **kw: result)
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
