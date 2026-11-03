"""Offline coverage for metadata-preserving generic HTTP responses."""

from __future__ import annotations

from http import HTTPStatus

import pytest
import requests

from redfish_sdk import GenericResponse, RedfishClient


def _client() -> RedfishClient:
    return RedfishClient(
        "mock-bmc-host",
        "mock-user",
        "mock-password",
        verify_ssl=True,
    )


def _response(
    status: HTTPStatus,
    content: bytes = b"",
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = content
    response.encoding = "utf-8"
    response.headers.update(headers or {})
    response.request = requests.Request(
        "POST",
        "https://mock-bmc-host/redfish/v1/Actions/Example",
    ).prepare()
    return response


def test_post_preserves_empty_async_response_metadata(monkeypatch):
    client = _client()
    raw = _response(
        HTTPStatus.ACCEPTED,
        headers={
            "Location": "/redfish/v1/TaskService/TaskMonitors/7",
            "Retry-After": "12",
            "X-Vendor-Trace": "trace-7",
        },
    )
    monkeypatch.setattr(client._http_client, "post_raw", lambda *args: raw)

    result = client.post("/redfish/v1/Actions/Example", {})

    assert isinstance(result, GenericResponse)
    assert result.status_code == HTTPStatus.ACCEPTED
    assert result.headers["location"].endswith("/TaskMonitors/7")
    assert result.headers["X-VENDOR-TRACE"] == "trace-7"
    assert result.content == b""
    assert result.text == ""
    assert result.has_json is False
    assert result.json_data is None
    assert result.task_monitor.endswith("/TaskMonitors/7")
    assert result.retry_after == "12"
    assert result.as_dict() == {}
    assert result.json() == {}
    assert "trace-7" not in repr(result)
    client.close()


def test_patch_preserves_json_and_content_location(monkeypatch):
    client = _client()
    path = "/redfish/v1/Systems/1"
    client._http_client._last_etag[path] = '"etag"'
    raw = _response(
        HTTPStatus.OK,
        b'{"updated": true}',
        {"Content-Location": "/redfish/v1/Systems/1"},
    )
    monkeypatch.setattr(client._http_client, "patch_raw", lambda *args, **kwargs: raw)

    result = client.patch(path, {"AssetTag": "new-tag"})

    assert result.status_code == HTTPStatus.OK
    assert result.content_location == path
    assert result.has_json is True
    assert result.json_data == {"updated": True}
    assert result.json() == {"updated": True}
    assert result.as_dict() == {"updated": True}
    assert result["updated"] is True
    assert result.get("updated") is True
    assert result == {"updated": True}
    client.close()


def test_valid_json_null_is_distinct_from_decode_failure():
    result = GenericResponse.from_response(
        _response(HTTPStatus.OK, b"null", {"Content-Type": "application/json"})
    )

    assert result.has_json is True
    assert result.json_data is None
    assert result.json_error is None
    assert result.json() is None
    with pytest.raises(TypeError, match="not an object"):
        result.as_dict()


def test_delete_preserves_text_response(monkeypatch):
    client = _client()
    raw = _response(
        HTTPStatus.OK,
        b"deleted",
        {"Content-Type": "text/plain", "X-Delete-Mode": "soft"},
    )
    monkeypatch.setattr(client._http_client, "delete_raw", lambda *args: raw)

    result = client.delete("/redfish/v1/Oem/Vendor/Resource/1")

    assert result.status_code == HTTPStatus.OK
    assert result.headers["x-delete-mode"] == "soft"
    assert result.content == b"deleted"
    assert result.text == "deleted"
    assert result.has_json is False
    assert result.json_error is not None
    client.close()


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"not-json", "application/json"),
        (b"\x00\xff\x10binary", "application/octet-stream"),
    ],
    ids=["malformed-json", "binary"],
)
def test_post_keeps_non_json_body_inspectable(
    monkeypatch,
    content,
    content_type,
):
    client = _client()
    raw = _response(
        HTTPStatus.OK,
        content,
        {"Content-Type": content_type},
    )
    monkeypatch.setattr(client._http_client, "post_raw", lambda *args: raw)

    result = client.post("/redfish/v1/Oem/Vendor/Action", {})

    assert result.content == content
    assert isinstance(result.text, str)
    assert result.has_json is False
    assert result.json_data is None
    assert result.json_error is not None
    with pytest.raises(ValueError, match="not valid JSON"):
        result.json()
    client.close()
