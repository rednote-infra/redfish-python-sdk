"""Regression tests for the security and model defects tracked by issue #106."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishValidationError
from redfish_sdk.http_client import RedfishHttpClient, _redact_for_log
from redfish_sdk.models.account import Account
from redfish_sdk.models.chassis import Chassis
from redfish_sdk.models.managers import SNMPCommunity, SnmpService
from redfish_sdk.models.registry import RegistryMessage
from redfish_sdk.models.session import Session
from redfish_sdk.models.systems import (
    GraphicalConsoleGetOneTimeURLResponse,
    GraphicalConsoleSetOneTimePasswordResponse,
    GraphicalConsoleSetPasswordRequest,
)


def _response(
    status: int = 200,
    *,
    body: bytes = b"payload",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body
    response.headers.update(headers or {})
    response.request = requests.Request("GET", "https://bmc.example/resource").prepare()
    return response


def test_tls_verification_is_enabled_by_default() -> None:
    client = RedfishClient("bmc.example", "admin", "password")
    try:
        assert client._http_client.verify_ssl is True
        assert client._http_client._session.verify is True
    finally:
        client.close()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"scheme": "http"}, "require HTTPS"),
        ({"scheme": "ftp"}, "scheme"),
        ({"host": "user:pass@bmc.example"}, "hostname or IP"),
        ({"host": "bmc.example/redfish/v1"}, "hostname or IP"),
        ({"host": "bmc.example?token=value"}, "hostname or IP"),
        ({"host": "bmc.example:invalid"}, "host or port"),
        ({"host": " bmc.example"}, "non-empty string"),
        ({"username": "domain:admin"}, "cannot contain ':'"),
    ],
)
def test_authenticated_endpoint_validation(kwargs: dict, message: str) -> None:
    arguments = {"host": "bmc.example", "username": "admin", "password": "password"}
    arguments.update(kwargs)
    with pytest.raises(RedfishValidationError, match=message):
        RedfishClient(**arguments)


def test_plain_http_requires_an_explicit_compatibility_override() -> None:
    client = RedfishClient(
        "bmc.example",
        "admin",
        "password",
        scheme="http",
        allow_insecure_http_auth=True,
    )
    try:
        assert client._http_client.scheme == "http"
    finally:
        client.close()


@pytest.mark.parametrize("host", ["192.0.2.10", "bmc.example:8443", "[2001:db8::10]:8443"])
def test_supported_endpoint_forms(host: str) -> None:
    client = RedfishClient(host, "admin", "password")
    try:
        assert client._http_client.host == host
    finally:
        client.close()


def test_absolute_cross_origin_target_is_rejected_before_network_access() -> None:
    client = RedfishHttpClient("bmc.example", "admin", "password")
    client._session.get = Mock()

    with pytest.raises(RedfishValidationError, match="different origin"):
        client.download("https://files.example/artifact.bin")

    client._session.get.assert_not_called()


def test_requests_do_not_follow_redirects_implicitly() -> None:
    client = RedfishHttpClient("bmc.example", "admin", "password")
    client._session.get = Mock(return_value=_response())

    client._send("GET", "/redfish/v1/")

    assert client._session.get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    "filename",
    [
        "../escaped.tar.gz",
        "..\\escaped.tar.gz",
        "/absolute.tar.gz",
        ".",
        "..",
        "unsafe\x00name.tar.gz",
        "..%2Fescaped.tar.gz",
    ],
)
def test_content_disposition_cannot_escape_output_directory(
    tmp_path: Path, filename: str
) -> None:
    client = RedfishHttpClient("bmc.example", "admin", "password")
    client._request = Mock(
        return_value=_response(
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    )
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()

    with pytest.raises(RedfishValidationError, match="Unsafe filename"):
        client.download_via_post("/redfish/v1/Download", f"{output_dir}/")

    assert list(tmp_path.rglob("*.tar.gz")) == []


def test_safe_content_disposition_filename_is_written_inside_directory(
    tmp_path: Path,
) -> None:
    client = RedfishHttpClient("bmc.example", "admin", "password")
    client._request = Mock(
        return_value=_response(
            headers={"Content-Disposition": 'attachment; filename="bundle.tar.gz"'}
        )
    )
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()

    result = client.download_via_post("/redfish/v1/Download", f"{output_dir}/")

    assert Path(result) == output_dir / "bundle.tar.gz"
    assert (output_dir / "bundle.tar.gz").read_bytes() == b"payload"


def test_sensitive_key_suffixes_are_redacted() -> None:
    secret = "never-log-this-secret"
    payload = {
        "AuthPassword": secret,
        "PrivPassword": secret,
        "SnmpV3AuthPassword": secret,
        "SnmpV3PrivPassword": secret,
        "ReadOnlyCommunity": secret,
        "Nested": {"X-Auth-Token": secret},
    }

    redacted = repr(_redact_for_log(payload))

    assert secret not in redacted
    assert redacted.count("<redacted>") == 6


def test_sensitive_payload_values_do_not_reach_info_logs(caplog) -> None:
    secret = "never-log-this-secret"
    client = RedfishHttpClient("bmc.example", "admin", "password")
    client._request = Mock(return_value=_response(body=b"{}"))

    with caplog.at_level(logging.INFO):
        client.post_raw(
            "/redfish/v1/example",
            {"SnmpV3AuthPassword": secret, "ReadOnlyCommunity": secret},
        )

    assert secret not in caplog.text


@pytest.mark.parametrize(
    "model",
    [
        Account(password="account-secret"),
        Session(password="session-secret", x_auth_token="token-secret"),
        SNMPCommunity(community_string="community-secret"),
        SnmpService(
            read_only_community="community-secret",
            snmp_v3_auth_password="auth-secret",
            snmp_v3_priv_password="priv-secret",
        ),
        GraphicalConsoleSetPasswordRequest(
            console_type="KVMIP", password="console-secret"
        ),
        GraphicalConsoleGetOneTimeURLResponse(
            console_type="KVMIP",
            access_mode="ReadWrite",
            console_url="https://bmc.example/secret",
        ),
        GraphicalConsoleSetOneTimePasswordResponse(
            console_type="KVMIP",
            access_mode="ReadWrite",
            password="one-time-secret",
        ),
    ],
)
def test_secret_bearing_models_hide_values_from_repr(model) -> None:
    representation = repr(model)
    assert "secret" not in representation


def test_chassis_accepts_top_level_pcie_device_arrays() -> None:
    chassis = Chassis.model_validate(
        {
            "Id": "Chassis-1",
            "PCIeDevices": [
                {"@odata.id": "/redfish/v1/Chassis/Chassis-1/PCIeDevices/1"}
            ],
        }
    )

    assert isinstance(chassis.pcie_devices, list)
    assert chassis.pcie_devices[0].odata_id.endswith("/PCIeDevices/1")


def test_registry_message_exposes_optional_example_for_mislabeled_documents() -> None:
    message = RegistryMessage.model_validate(
        {
            "Description": "Example-bearing message from a mislabeled registry",
            "Message": "A message",
            "Example": "An example",
        }
    )

    assert message.example == "An example"
    assert RegistryMessage.model_validate({"Message": "Legacy"}).example is None
