"""Offline coverage for public TLS trust and caller-owned Requests transports."""
from __future__ import annotations

import asyncio
import json
import shutil
import ssl
import subprocess
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock, patch

import pytest
import requests

from redfish_sdk import (
    AsyncRedfishClient,
    AuthenticationMode,
    RedfishClient,
    RedfishConnectionError,
    RedfishServiceUnavailableError,
    RedfishValidationError,
)
from redfish_sdk.http_client import RedfishHttpClient

HOST = "bmc.example"
ROOT = "/redfish/v1/"
SESSIONS = "/redfish/v1/SessionService/Sessions"
LOCATION = f"{SESSIONS}/example"


def response(status=200, data=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps({} if data is None else data).encode()
    result._content_consumed = True
    result.headers.update(headers or {})
    return result


class RecordingAdapter(requests.adapters.BaseAdapter):
    def __init__(self, handler=None):
        self.handler = handler or (lambda request: response(data={"ok": True}))
        self.calls = []
        self.close_calls = 0
        self.context = ssl.create_default_context()

    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        result = self.handler(request)
        result.request = request
        result.url = request.url
        return result

    def close(self):
        self.close_calls += 1


def configured_session(handler=None):
    session = requests.Session()
    session.trust_env = False
    session.headers["X-Trace"] = "trace-example"
    adapter = RecordingAdapter(handler)
    session.mount("https://", adapter)
    return session, adapter


def test_public_ca_bundle_preserves_boolean_signature_and_does_not_suppress_warnings(tmp_path):
    ca = tmp_path / "ca.pem"
    with warnings.catch_warnings():
        before = list(warnings.filters)
        client = RedfishClient(HOST, "user", "password", ca_bundle=ca)
        try:
            assert client._http_client.verify_ssl == str(ca)
            assert client._http_client._session.verify == str(ca)
            assert client._http_client._external_session.verify == str(ca)
            assert warnings.filters == before
        finally:
            client.close()


def test_injected_session_preserves_configuration_and_is_not_closed():
    session, adapter = configured_session()
    session.verify = "/enterprise/ca.pem"
    session.proxies = {"https": "http://proxy.example:8080"}
    session.cert = ("/enterprise/client.pem", "/enterprise/client.key")
    session.cookies.set("preference", "example", domain=HOST, path="/")
    traced = []
    session.hooks["response"].append(lambda result, **kwargs: traced.append(result.status_code))
    snapshot = (dict(session.headers), dict(session.proxies), session.verify, session.auth)
    context = adapter.context
    try:
        with RedfishClient(HOST, "user", "password", session=session,
                           connect_timeout=4, read_timeout=19) as client:
            assert client.request("GET", ROOT)["ok"] is True
        request, options = adapter.calls[0]
        assert request.headers["X-Trace"] == "trace-example"
        assert request.headers["Authorization"].startswith("Basic ")
        assert options["verify"] == "/enterprise/ca.pem"
        assert options["timeout"] == (4, 19)
        assert options["proxies"]["https"] == "http://proxy.example:8080"
        assert options["cert"] == session.cert
        assert request.headers["Cookie"] == "preference=example"
        assert traced == [200]
        assert adapter.context is context
        assert adapter.close_calls == 0
        assert (dict(session.headers), dict(session.proxies), session.verify, session.auth) == snapshot
    finally:
        session.close()
    assert adapter.close_calls == 1


def test_explicit_ca_proxy_and_timeout_override_session_without_mutation(tmp_path):
    session, adapter = configured_session()
    session.verify = False
    session.proxies = {"https": "http://old-proxy.example:8080"}
    ca = tmp_path / "private-ca.pem"
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session, ca_bundle=ca,
                               proxy="http://new-proxy.example:8080") as client:
            client.request("GET", ROOT, read_timeout=75)
        options = adapter.calls[0][1]
        assert options["verify"] == str(ca)
        assert options["timeout"] == (10, 75)
        assert options["proxies"]["https"] == "http://new-proxy.example:8080"
        assert session.verify is False
        assert session.proxies["https"] == "http://old-proxy.example:8080"
    finally:
        session.close()


@pytest.mark.parametrize("header", ["Authorization", "x-auth-token"])
def test_injected_authentication_headers_are_rejected(header):
    with requests.Session() as session:
        session.headers[header] = "conflicting-authentication"
        with pytest.raises(RedfishValidationError):
            RedfishHttpClient(HOST, "user", "password", session=session)


def test_injected_default_auth_and_shared_external_transport_are_rejected():
    with requests.Session() as session:
        session.auth = ("another-user", "another-password")
        with pytest.raises(RedfishValidationError):
            RedfishClient(HOST, "user", "password", session=session)
        session.auth = None
        with pytest.raises(RedfishValidationError):
            RedfishClient(HOST, "user", "password", session=session, external_session=session)


def test_injected_auth_changes_after_construction_are_rejected():
    session, adapter = configured_session()
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session) as client:
            session.headers["X-Auth-Token"] = "unexpected-token"
            with pytest.raises(RedfishValidationError):
                client.get_raw(ROOT)
        assert adapter.calls == []
    finally:
        session.close()


def test_netrc_cannot_replace_sdk_authentication():
    session, adapter = configured_session()
    session.trust_env = True
    try:
        with patch("requests.sessions.get_netrc_auth", return_value=("wrong-user", "wrong-password")) as lookup, \
                RedfishHttpClient(HOST, "user", "password", session=session) as client:
            client.get_raw(ROOT)
        lookup.assert_not_called()
        assert adapter.calls[0][0].headers["Authorization"] == client._basic_auth
    finally:
        session.close()


def test_refresh_uses_injected_pool_without_sending_old_credentials_or_mutating_headers():
    def handler(request):
        if request.method == "POST":
            assert "Authorization" not in request.headers
            assert "X-Auth-Token" not in request.headers
            return response(201, headers={"X-Auth-Token": "new-token", "Location": LOCATION})
        if request.method == "DELETE":
            return response(204)
        if request.headers.get("X-Auth-Token") == "old-token":
            return response(401)
        assert request.headers["X-Auth-Token"] == "new-token"
        return response(data={"ok": True})
    session, adapter = configured_session(handler)
    initial_headers = dict(session.headers)
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session,
                auth_mode=AuthenticationMode.SESSION, session_key="old-token", session_location=LOCATION) as client:
            assert client.get_raw(ROOT)["ok"] is True
        assert [request.method for request, _ in adapter.calls] == ["GET", "POST", "GET", "DELETE"]
        assert dict(session.headers) == initial_headers
        assert adapter.close_calls == 0
    finally:
        session.close()


def test_injected_transport_never_automatically_follows_redirects():
    session, adapter = configured_session(lambda request: response(307, headers={"Location": "https://other.example/"}))
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session) as client:
            assert client.request("POST", ROOT, body={"Secret": "example"}).status_code == 307
        assert len(adapter.calls) == 1
        assert adapter.calls[0][0].url.startswith(f"https://{HOST}/")
    finally:
        session.close()


def test_explicit_same_origin_redirects_remain_available():
    def handler(request):
        if request.url.endswith(ROOT):
            return response(307, headers={"Location": f"{ROOT}Systems"})
        return response(data={"ok": True})
    session, adapter = configured_session(handler)
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session) as client:
            assert client.request("GET", ROOT, allow_redirects=True)["ok"] is True
        assert len(adapter.calls) == 2
    finally:
        session.close()


def test_cross_origin_download_uses_separate_caller_owned_transport():
    session, bmc_adapter = configured_session()
    external, external_adapter = configured_session()
    external.verify = "/publication/ca.pem"
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session, external_session=external) as client:
            client.set_auth_token("bmc-token")
            assert client.download("https://files.example/log.bin") == b'{"ok": true}'
        request, options = external_adapter.calls[0]
        assert "Authorization" not in request.headers
        assert "X-Auth-Token" not in request.headers
        assert options["verify"] == "/publication/ca.pem"
        assert bmc_adapter.calls == []
        assert bmc_adapter.close_calls == external_adapter.close_calls == 0
    finally:
        session.close()
        external.close()


def test_owned_sessions_are_closed_and_caller_owned_sessions_survive_errors():
    client = RedfishHttpClient(HOST, "user", "password", verify_ssl=True)
    client._session.close = Mock()
    client._external_session.close = Mock()
    client.close()
    client._session.close.assert_called_once()
    client._external_session.close.assert_called_once()
    session, adapter = configured_session(lambda request: response(503))
    try:
        with pytest.raises(RedfishServiceUnavailableError), RedfishHttpClient(HOST, "user", "password", session=session) as client:
            client.get_raw(ROOT)
        assert adapter.close_calls == 0
    finally:
        session.close()


@pytest.mark.parametrize("value", ["", " ", b"ca.pem", False, object()])
def test_invalid_ca_bundle_is_rejected(value):
    with pytest.raises(RedfishValidationError):
        RedfishClient(HOST, "user", "password", ca_bundle=value)


def test_explicit_verification_can_be_enabled_for_an_insecure_injected_session():
    session, adapter = configured_session()
    session.verify = False
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session, verify_ssl=True) as client:
            client.get_raw(ROOT)
        assert adapter.calls[0][1]["verify"] is True
        assert session.verify is False
    finally:
        session.close()


def test_legacy_runtime_verify_path_is_preserved():
    with RedfishHttpClient(HOST, "user", "password", verify_ssl="/enterprise/ca.pem") as client:
        assert client.verify_ssl == "/enterprise/ca.pem"


@pytest.fixture
def private_ca_server(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("Local TLS verification requires the OpenSSL command")
    key, cert = tmp_path / "server.key", tmp_path / "ca.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("localhost", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"localhost:{server.server_port}", cert
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_private_ca_verifies_a_real_local_https_connection(private_ca_server):
    host, cert = private_ca_server
    with requests.Session() as session:
        session.trust_env = False
        with RedfishClient(host, "test-user", "test-password", session=session, ca_bundle=cert) as client:
            assert client.request("GET", ROOT)["ok"] is True
    with requests.Session() as session:
        session.trust_env = False
        with pytest.raises(RedfishConnectionError), RedfishClient(
                host, "test-user", "test-password", session=session, verify_ssl=True) as client:
            client.request("GET", ROOT)


@pytest.mark.parametrize("header", ["Authorization", "X-Auth-Token"])
def test_external_session_credentials_are_rejected(header):
    with requests.Session() as external:
        external.headers[header] = "external-credential"
        with pytest.raises(RedfishValidationError):
            RedfishClient(HOST, "user", "password", external_session=external)


def test_cross_origin_explicit_redirect_rejected_before_sending_a_write():
    session, adapter = configured_session(lambda request: response(307, headers={"Location": "https://other.example/"}))
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session) as client, pytest.raises(RedfishValidationError):
            client.request("POST", ROOT, body={"Password": "dummy"}, allow_redirects=True)
        assert len(adapter.calls) == 1
    finally:
        session.close()


def test_explicit_ca_bundle_wins_over_environment_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/environment/other-ca.pem")
    session, adapter = configured_session()
    session.trust_env = True
    ca = tmp_path / "explicit-ca.pem"
    try:
        with RedfishHttpClient(HOST, "user", "password", session=session, ca_bundle=ca) as client:
            client.get_raw(ROOT)
        assert adapter.calls[0][1]["verify"] == str(ca)
        assert session.verify is True
    finally:
        session.close()


def test_custom_https_adapter_pool_configuration_is_preserved():
    context = ssl.create_default_context()
    class ContextAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
            super().init_poolmanager(connections, maxsize, block=block, ssl_context=context, **kwargs)
    with requests.Session() as session:
        adapter = ContextAdapter(pool_connections=3, pool_maxsize=7, pool_block=True)
        session.mount("https://", adapter)
        with RedfishClient(HOST, "user", "password", session=session):
            assert session.get_adapter(f"https://{HOST}") is adapter
            assert adapter.poolmanager.connection_pool_kw["ssl_context"] is context
            assert adapter.poolmanager.connection_pool_kw["maxsize"] == 7
            assert adapter.poolmanager.connection_pool_kw["block"] is True


def test_bmc_client_certificate_and_cookies_are_not_copied_to_default_external_session():
    with requests.Session() as session:
        session.cert = ("/enterprise/client.pem", "/enterprise/client.key")
        session.cookies.set("bmc-preference", "example", domain=HOST)
        with RedfishHttpClient(HOST, "user", "password", session=session) as client:
            assert client._external_session.cert is None
            assert not client._external_session.cookies


def test_refresh_does_not_send_credentials_to_the_external_artifact_transport():
    external, external_adapter = configured_session()
    def handler(request):
        if request.method == "POST":
            assert "Authorization" not in request.headers
            assert "X-Auth-Token" not in request.headers
            return response(201, headers={"X-Auth-Token": "new-token", "Location": LOCATION})
        if request.method == "DELETE":
            return response(204)
        if request.headers.get("X-Auth-Token") == "old-token":
            return response(401)
        return response(data={"ok": True})
    adapter = RecordingAdapter(handler)
    try:
        with RedfishHttpClient(HOST, "user", "password", verify_ssl=True,
                external_session=external, session_key="old-token", session_location=LOCATION) as client:
            client._session.mount("https://", adapter)
            assert client.get_raw(ROOT)["ok"] is True
        assert external_adapter.calls == []
        assert external_adapter.close_calls == 0
    finally:
        external.close()


@pytest.mark.parametrize("source", ["headers", "auth"])
def test_async_transport_rejects_credentials_added_after_construction(source):
    session, adapter = configured_session()
    async def run():
        async with AsyncRedfishClient(HOST, "user", "password", session=session,
                                      auth_mode=AuthenticationMode.BASIC) as client:
            if source == "headers":
                session.headers["X-Auth-Token"] = "unexpected-token"
            else:
                session.auth = ("another-user", "another-password")
            with pytest.raises(RedfishValidationError):
                await client.get(ROOT)
    try:
        asyncio.run(run())
        assert adapter.calls == []
    finally:
        session.close()
