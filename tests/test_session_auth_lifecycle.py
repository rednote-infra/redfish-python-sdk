"""Offline coverage for Redfish session authentication lifecycle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import AuthenticationMode, RedfishClient
from redfish_sdk.exceptions import (
    RedfishAsyncOperationError,
    RedfishAuthError,
    RedfishValidationError,
)
from redfish_sdk.http_client import RedfishHttpClient
from redfish_sdk.models.common import Link
from redfish_sdk.models.root import RootLinks, RootService
from redfish_sdk.models.session import Session


def _response(
    status: int,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
    *,
    method: str = "GET",
    url: str = "https://bmc.example/redfish/v1/",
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body
    response.headers.update(headers or {})
    response.request = requests.Request(method, url).prepare()
    return response


def _http(**kwargs) -> RedfishHttpClient:
    return RedfishHttpClient(
        "bmc.example",
        "user",
        "password",
        verify_ssl=True,
        **kwargs,
    )


def test_explicit_auth_modes_and_existing_session_state():
    basic = _http(auth_mode=AuthenticationMode.BASIC)
    assert basic.auth_mode is AuthenticationMode.BASIC
    assert "Authorization" in basic._session.headers
    assert "X-Auth-Token" not in basic._session.headers
    basic.close()

    session = _http(
        auth_mode=AuthenticationMode.SESSION,
        session_key="existing-token",
        session_location="/redfish/v1/SessionService/Sessions/9",
    )
    assert session.auth_mode is AuthenticationMode.SESSION
    assert session._session_key == "existing-token"
    assert session.session_location.endswith("/Sessions/9")
    assert "Authorization" not in session._session.headers
    assert session._session.headers["X-Auth-Token"] == "existing-token"
    session._session.delete = Mock(return_value=_response(204, method="DELETE"))
    session.close()


def test_legacy_string_auth_mode_is_normalized_to_enum():
    http = _http(auth_mode=AuthenticationMode.SESSION.value)

    assert http.auth_mode is AuthenticationMode.SESSION
    http.close()


@pytest.mark.parametrize("auth_mode", ["", "token", "SESSION"])
def test_invalid_auth_mode_is_rejected(auth_mode):
    with pytest.raises(RedfishValidationError, match="auth_mode"):
        _http(auth_mode=auth_mode)


def test_session_creation_accepts_header_only_201(monkeypatch):
    client = RedfishClient(
        "bmc.example", "user", "password", verify_ssl=True
    )
    sessions_uri = "/redfish/v1/SessionService/Sessions"
    location = f"{sessions_uri}/42"
    root = RootService.model_construct(
        links=RootLinks.model_construct(
            sessions=Link.model_construct(odata_id=sessions_uri)
        )
    )
    monkeypatch.setattr(client, "_get_root", lambda: root)
    monkeypatch.setattr(
        client._http_client,
        "post_raw",
        lambda path, body=None: _response(
            201,
            headers={"X-Auth-Token": "new-token", "Location": location},
            method="POST",
        ),
    )

    session = client.create_session(
        "session-user", "session-password", switch_to_token_auth=True
    )

    assert session.odata_id == location
    assert session.id == "42"
    assert session.x_auth_token == "new-token"
    assert client._http_client._session_key == "new-token"
    assert client._http_client.session_location == location
    client._http_client._session.delete = Mock(
        return_value=_response(204, method="DELETE")
    )
    client.close()


def test_safe_read_refreshes_expired_session_once(monkeypatch):
    http = _http(
        auth_mode=AuthenticationMode.SESSION,
        session_key="expired-token",
        session_location="/redfish/v1/SessionService/Sessions/1",
    )
    get = Mock(
        side_effect=[
            _response(401),
            _response(200, b'{"ok": true}'),
        ]
    )
    login = Mock(
        return_value=_response(
            201,
            headers={
                "X-Auth-Token": "refreshed-token",
                "Location": "/redfish/v1/SessionService/Sessions/2",
            },
            method="POST",
        )
    )
    monkeypatch.setattr(http._session, "get", get)
    monkeypatch.setattr(http._external_session, "post", login)

    assert http.get_raw("/redfish/v1/Systems") == {"ok": True}
    assert get.call_count == 2
    assert login.call_count == 1
    assert http._session_key == "refreshed-token"
    assert http.session_location.endswith("/Sessions/2")
    http._session.delete = Mock(return_value=_response(204, method="DELETE"))
    http.close()


def test_session_mode_without_key_logs_in_before_first_read(monkeypatch):
    http = _http(auth_mode=AuthenticationMode.SESSION)
    login = Mock(
        return_value=_response(
            201,
            headers={
                "X-Auth-Token": "initial-token",
                "Location": "/redfish/v1/SessionService/Sessions/1",
            },
            method="POST",
        )
    )
    get = Mock(return_value=_response(200, b'{"ok": true}'))
    monkeypatch.setattr(http._external_session, "post", login)
    monkeypatch.setattr(http._session, "get", get)

    assert http.get_raw("/redfish/v1/") == {"ok": True}
    assert login.call_count == 1
    assert get.call_count == 1
    assert http._session_key == "initial-token"
    http._session.delete = Mock(return_value=_response(204, method="DELETE"))
    http.close()


def test_failed_refresh_does_not_loop_or_fall_back(monkeypatch):
    http = _http(
        auth_mode=AuthenticationMode.SESSION,
        session_key="expired-token",
        session_location="/redfish/v1/SessionService/Sessions/1",
    )
    get = Mock(return_value=_response(401))
    login = Mock(return_value=_response(401, method="POST"))
    monkeypatch.setattr(http._session, "get", get)
    monkeypatch.setattr(http._external_session, "post", login)

    with pytest.raises(RedfishAuthError):
        http.get_raw("/redfish/v1/Systems")

    assert get.call_count == 1
    assert login.call_count == 1
    assert http.auth_mode is AuthenticationMode.SESSION
    assert "Authorization" not in http._session.headers
    http._session.delete = Mock(return_value=_response(500, method="DELETE"))
    http.close()


def test_task_polling_does_not_fall_back_after_session_refresh_failure(
    monkeypatch,
):
    client = RedfishClient(
        "bmc.example", "user", "password", verify_ssl=True
    )
    client._http_client.set_auth_token("expired-token")
    get = Mock(side_effect=RedfishAuthError(401))
    monkeypatch.setattr(client._tasks, "get", get)

    with pytest.raises(RedfishAsyncOperationError, match="session refresh"):
        client.wait_for_task("7", timeout=1)

    assert get.call_count == 1
    assert client._http_client.auth_mode is AuthenticationMode.SESSION
    assert "Authorization" not in client._http_client._session.headers
    client.close()


def test_state_changing_request_is_not_refreshed_or_replayed(monkeypatch):
    http = _http(
        auth_mode=AuthenticationMode.SESSION,
        session_key="expired-token",
    )
    post = Mock(return_value=_response(401, method="POST"))
    login = Mock()
    monkeypatch.setattr(http._session, "post", post)
    monkeypatch.setattr(http._external_session, "post", login)

    with pytest.raises(RedfishAuthError):
        http.post_raw("/redfish/v1/Systems/1/Actions/Reset", body={})

    assert post.call_count == 1
    login.assert_not_called()
    http.close()


@pytest.mark.parametrize("header", ["Authorization", "X-Auth-Token", "x-auth-token"])
def test_per_request_headers_cannot_replace_managed_auth(header):
    http = _http()
    http._session.get = Mock()

    with pytest.raises(RedfishValidationError, match="managed authentication"):
        http._request("GET", "/redfish/v1/", headers={header: "replacement"})

    http._session.get.assert_not_called()
    http.close()


def test_concurrent_401_responses_share_one_refresh(monkeypatch):
    http = _http(
        auth_mode=AuthenticationMode.SESSION,
        session_key="expired-token",
        session_location="/redfish/v1/SessionService/Sessions/1",
    )
    barrier = Barrier(2)
    state_lock = Lock()
    initial_calls = 0

    def get(url, **kwargs):
        nonlocal initial_calls
        with state_lock:
            if initial_calls < 2:
                initial_calls += 1
                initial = True
            else:
                initial = False
        if initial:
            barrier.wait(timeout=5)
            return _response(401)
        return _response(200, b'{"ok": true}')

    login = Mock(
        return_value=_response(
            201,
            headers={
                "X-Auth-Token": "shared-token",
                "Location": "/redfish/v1/SessionService/Sessions/2",
            },
            method="POST",
        )
    )
    monkeypatch.setattr(http._session, "get", get)
    monkeypatch.setattr(http._external_session, "post", login)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: http.get_raw("/redfish/v1/Systems"), range(2))
        )

    assert results == [{"ok": True}, {"ok": True}]
    assert login.call_count == 1
    http._session.delete = Mock(return_value=_response(204, method="DELETE"))
    http.close()


def test_concurrent_401_responses_share_one_failed_refresh(monkeypatch):
    http = _http(
        auth_mode=AuthenticationMode.SESSION,
        session_key="expired-token",
        session_location="/redfish/v1/SessionService/Sessions/1",
    )
    barrier = Barrier(2)

    def get(url, **kwargs):
        barrier.wait(timeout=5)
        return _response(401)

    login = Mock(return_value=_response(401, method="POST"))
    monkeypatch.setattr(http._session, "get", get)
    monkeypatch.setattr(http._external_session, "post", login)

    def read_systems():
        with pytest.raises(RedfishAuthError):
            http.get_raw("/redfish/v1/Systems")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: read_systems(), range(2)))

    assert login.call_count == 1
    assert http.auth_mode is AuthenticationMode.SESSION
    assert "Authorization" not in http._session.headers
    http._session.delete = Mock(return_value=_response(500, method="DELETE"))
    http.close()


@pytest.mark.parametrize("delete_status", [204, 500])
def test_close_always_clears_auth_state_and_closes_local_sessions(delete_status):
    http = _http(
        auth_mode=AuthenticationMode.SESSION,
        session_key="active-token",
        session_location="/redfish/v1/SessionService/Sessions/1",
    )
    http._session.delete = Mock(
        return_value=_response(delete_status, method="DELETE")
    )
    local_close = Mock()
    external_close = Mock()
    http._session.close = local_close
    http._external_session.close = external_close

    http.close()

    http._session.delete.assert_called_once()
    assert http.auth_mode is AuthenticationMode.BASIC
    assert http._session_key is None
    assert http.session_location is None
    assert "X-Auth-Token" not in http._session.headers
    assert "Authorization" in http._session.headers
    local_close.assert_called_once_with()
    external_close.assert_called_once_with()


def test_deleting_active_session_restores_basic_auth(monkeypatch):
    client = RedfishClient(
        "bmc.example", "user", "password", verify_ssl=True
    )
    location = "/redfish/v1/SessionService/Sessions/7"
    active = Session.model_construct(id="7", odata_id=location)
    client._http_client.set_auth_token("active-token", session_location=location)
    monkeypatch.setattr(client._sessions, "sessions", lambda: [active])
    delete = Mock(return_value="")
    monkeypatch.setattr(client._http_client, "delete", delete)

    client.delete_session("7")

    delete.assert_called_once_with(location)
    assert client._http_client.auth_mode is AuthenticationMode.BASIC
    assert client._http_client._session_key is None
    assert "Authorization" in client._http_client._session.headers
    client.close()
