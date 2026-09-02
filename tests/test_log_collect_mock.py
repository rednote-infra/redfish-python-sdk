"""
Mock tests for out-of-band diagnostic log collection + download.

Covers:
  - collect_diagnostic_data: action discovery, vendor default body,
    explicit type override, oem_params merge, missing-action error.
  - download_diagnostic_data: URI resolution from Task/LogEntry, bytes vs
    file output, missing-URI error.
  - collect_and_download_diagnostic_data: end-to-end chaining and task
    failure handling.
  - Multi-vendor strategy registration + generic fallback.
  - RedfishHttpClient.download: relative/absolute URI, bytes and file modes.
  - LogEntry.additional_data_uri model field.

These tests never hit a real BMC; HTTP calls are stubbed via monkeypatch.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pytest

from redfish_sdk import LogEntry, RedfishClient, RedfishValidationError
from redfish_sdk.exceptions import RedfishException
from redfish_sdk.models.common import Link
from redfish_sdk.models.logs import Log
from redfish_sdk.models.task import Task
from redfish_sdk.managers.log_collect_strategies import (
    GenericLogCollectStrategy,
    LogCollectStrategyRegistry,
    XFusionLogCollectStrategy,
)

MOCK_HOST = os.environ.get("BMC_IP", "mock-bmc-host")
MOCK_USER = os.environ.get("BMC_USER", "mock-user")
MOCK_PASSWORD = os.environ.get("BMC_PASSWORD", "mock-password")

COLLECT_TARGET = (
    "/redfish/v1/Managers/1/LogServices/Log1/Actions/"
    "LogService.CollectDiagnosticData"
)


def _make_client() -> RedfishClient:
    return RedfishClient(host=MOCK_HOST, username=MOCK_USER, password=MOCK_PASSWORD)


class _CallRecorder:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    @property
    def last(self) -> Dict[str, Any]:
        assert self.calls, "no call recorded"
        return self.calls[-1]


def _stub_manager(monkeypatch, client) -> None:
    from redfish_sdk.models.managers import Manager

    manager = Manager.model_construct(
        id="1",
        odata_id="/redfish/v1/Managers/1",
        log_services=Link(**{"@odata.id": "/redfish/v1/Managers/1/LogServices"}),
    )
    monkeypatch.setattr(client._managers, "get", lambda manager_id="1": manager)


def _stub_log_service(monkeypatch, client, *, actions) -> None:
    log = Log.model_construct(
        id="Log1",
        odata_id="/redfish/v1/Managers/1/LogServices/Log1",
        actions=actions,
    )
    monkeypatch.setattr(
        client, "_get_collection",
        lambda odata_id, mc: [log] if mc is Log else [],
    )


def _force_vendor(monkeypatch, vendor: str) -> None:
    from redfish_sdk.managers.log_collect_strategies import VendorDetector

    monkeypatch.setattr(VendorDetector, "detect", classmethod(lambda cls, c: vendor))


# ---------------------------------------------------------------------------
# collect_diagnostic_data
# ---------------------------------------------------------------------------


class TestCollectDiagnosticData:
    def test_generic_default_body(self, monkeypatch):
        client = _make_client()
        _stub_manager(monkeypatch, client)
        _stub_log_service(
            monkeypatch, client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor(monkeypatch, "generic")

        recorder = _CallRecorder()

        def fake_post(path, model_class, body=None, raw_body=None):
            recorder.record(path=path, raw_body=raw_body)
            return Task.model_construct(id="42", odata_id="/redfish/v1/TaskService/Tasks/42")

        monkeypatch.setattr(client._http_client, "post", fake_post)

        task = client.collect_diagnostic_data()
        assert recorder.last["path"] == COLLECT_TARGET
        assert recorder.last["raw_body"] == {"DiagnosticDataType": "Manager"}
        assert task.id == "42"
        client.close()

    def test_explicit_type_overrides_default(self, monkeypatch):
        client = _make_client()
        _stub_manager(monkeypatch, client)
        _stub_log_service(
            monkeypatch, client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor(monkeypatch, "xfusion")  # default would be OEM

        recorder = _CallRecorder()
        monkeypatch.setattr(
            client._http_client, "post",
            lambda path, mc, body=None, raw_body=None: (
                recorder.record(raw_body=raw_body) or Task.model_construct(id="1")
            ),
        )

        client.collect_diagnostic_data(diagnostic_data_type="Manager")
        assert recorder.last["raw_body"]["DiagnosticDataType"] == "Manager"
        client.close()

    def test_oem_params_merged(self, monkeypatch):
        client = _make_client()
        _stub_manager(monkeypatch, client)
        _stub_log_service(
            monkeypatch, client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor(monkeypatch, "generic")

        recorder = _CallRecorder()
        monkeypatch.setattr(
            client._http_client, "post",
            lambda path, mc, body=None, raw_body=None: (
                recorder.record(raw_body=raw_body) or Task.model_construct(id="1")
            ),
        )

        client.collect_diagnostic_data(oem_params={"OEMDiagnosticDataType": "Full"})
        assert recorder.last["raw_body"]["OEMDiagnosticDataType"] == "Full"
        client.close()

    def test_missing_action_raises(self, monkeypatch):
        client = _make_client()
        _stub_manager(monkeypatch, client)
        _stub_log_service(monkeypatch, client, actions=None)

        with pytest.raises(RedfishValidationError, match="CollectDiagnosticData"):
            client.collect_diagnostic_data()
        client.close()


# ---------------------------------------------------------------------------
# download_diagnostic_data
# ---------------------------------------------------------------------------


class TestDownloadDiagnosticData:
    def test_from_log_entry_bytes(self, monkeypatch):
        client = _make_client()
        entry = LogEntry.model_construct(
            id="1", additional_data_uri="/redfish/v1/download/bundle.tar.gz"
        )

        recorder = _CallRecorder()

        def fake_download(uri, output_path=None, chunk_size=65536):
            recorder.record(uri=uri, output_path=output_path)
            return b"BUNDLE"

        monkeypatch.setattr(client._http_client, "download", fake_download)

        data = client.download_diagnostic_data(entry)
        assert data == b"BUNDLE"
        assert recorder.last["uri"] == "/redfish/v1/download/bundle.tar.gz"
        assert recorder.last["output_path"] is None
        client.close()

    def test_from_task_resolves_uri(self, monkeypatch):
        client = _make_client()
        _force_vendor(monkeypatch, "generic")
        task = Task.model_construct(
            id="42", odata_id="/redfish/v1/TaskService/Tasks/42"
        )

        # Generic strategy resolves via raw task body AdditionalDataURI.
        monkeypatch.setattr(
            client._http_client, "get_raw",
            lambda path: {
                "Id": "42",
                "AdditionalDataURI": "/redfish/v1/download/42.tar.gz",
            },
        )

        recorder = _CallRecorder()
        monkeypatch.setattr(
            client._http_client, "download",
            lambda uri, output_path=None, chunk_size=65536: (
                recorder.record(uri=uri, output_path=output_path) or "/tmp/42.tar.gz"
            ),
        )

        path = client.download_diagnostic_data(task, output_path="/tmp/42.tar.gz")
        assert path == "/tmp/42.tar.gz"
        assert recorder.last["uri"] == "/redfish/v1/download/42.tar.gz"
        client.close()

    def test_missing_uri_raises(self, monkeypatch):
        client = _make_client()
        entry = LogEntry.model_construct(id="1", additional_data_uri=None)
        with pytest.raises(RedfishValidationError, match="download URI"):
            client.download_diagnostic_data(entry)
        client.close()


# ---------------------------------------------------------------------------
# collect_and_download_diagnostic_data
# ---------------------------------------------------------------------------


class TestCollectAndDownload:
    def test_end_to_end(self, monkeypatch):
        client = _make_client()
        _stub_manager(monkeypatch, client)
        _stub_log_service(
            monkeypatch, client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor(monkeypatch, "generic")

        monkeypatch.setattr(
            client._http_client, "post",
            lambda path, mc, body=None, raw_body=None: Task.model_construct(id="7"),
        )
        completed = Task.model_construct(
            id="7", task_state="Completed", task_status="OK",
            additional_data_uri="/redfish/v1/download/7.tar.gz",
        )
        monkeypatch.setattr(
            client, "wait_for_task",
            lambda task_id, poll_interval, timeout: completed,
        )
        monkeypatch.setattr(
            client._managers, "_resolve_diagnostic_download_uri",
            lambda t: "/redfish/v1/download/7.tar.gz",
        )
        monkeypatch.setattr(
            client._http_client, "download",
            lambda uri, output_path=None, chunk_size=65536: os.path.abspath(output_path),
        )

        path = client.collect_and_download_diagnostic_data("/tmp/7.tar.gz")
        assert path == os.path.abspath("/tmp/7.tar.gz")
        client.close()

    def test_task_failure_raises(self, monkeypatch):
        client = _make_client()
        _stub_manager(monkeypatch, client)
        _stub_log_service(
            monkeypatch, client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor(monkeypatch, "generic")

        monkeypatch.setattr(
            client._http_client, "post",
            lambda path, mc, body=None, raw_body=None: Task.model_construct(id="9"),
        )
        failed = Task.model_construct(id="9", task_state="Exception", task_status="Warning")
        monkeypatch.setattr(
            client, "wait_for_task",
            lambda task_id, poll_interval, timeout: failed,
        )

        with pytest.raises(RedfishException, match="did not succeed"):
            client.collect_and_download_diagnostic_data("/tmp/9.tar.gz")
        client.close()


# ---------------------------------------------------------------------------
# Strategy registry + vendor defaults
# ---------------------------------------------------------------------------


class TestStrategies:
    def test_registered_vendors(self):
        vendors = LogCollectStrategyRegistry.registered_vendors()
        for v in ("generic", "xfusion", "lenovo", "inspur", "nettrix", "zte"):
            assert v in vendors

    def test_unknown_vendor_falls_back_to_generic(self):
        strategy = LogCollectStrategyRegistry.get("does-not-exist")
        assert isinstance(strategy, GenericLogCollectStrategy)

    def test_generic_default_type(self):
        body = GenericLogCollectStrategy().build_body(None)
        assert body == {"DiagnosticDataType": "Manager"}

    def test_xfusion_oem_default(self):
        body = XFusionLogCollectStrategy().build_body(None)
        assert body["DiagnosticDataType"] == "OEM"
        assert body["OEMDiagnosticDataType"] == "Manager"


# ---------------------------------------------------------------------------
# RedfishHttpClient.download
# ---------------------------------------------------------------------------


class TestHttpDownload:
    def _fake_response(self, content: bytes, status: int = 200):
        class _Resp:
            status_code = status
            headers: Dict[str, str] = {}

            class request:  # noqa: N801 — mimic requests.Response.request
                method = "GET"

            def __init__(self, body: bytes):
                self._body = body

            @property
            def content(self) -> bytes:
                return self._body

            def iter_content(self, chunk_size: int = 65536):
                yield self._body

            @property
            def text(self) -> str:
                return ""

        return _Resp(content)

    def test_bytes_mode_and_relative_uri(self, monkeypatch):
        client = _make_client()
        http = client._http_client
        captured: Dict[str, Any] = {}

        def fake_get(url, stream=False, timeout=None):
            captured["url"] = url
            captured["stream"] = stream
            return self._fake_response(b"DATA")

        monkeypatch.setattr(http._session, "get", fake_get)

        data = http.download("/redfish/v1/download/x.bin")
        assert data == b"DATA"
        assert captured["url"] == f"https://{http.host}/redfish/v1/download/x.bin"
        assert captured["stream"] is True
        client.close()

    def test_file_mode_absolute_uri(self, monkeypatch, tmp_path):
        client = _make_client()
        http = client._http_client

        monkeypatch.setattr(
            http._session, "get",
            lambda url, stream=False, timeout=None: self._fake_response(b"HELLO"),
        )

        out = tmp_path / "sub" / "bundle.bin"
        path = http.download("https://files.example.com/bundle.bin", str(out))
        assert path == str(out)
        assert out.read_bytes() == b"HELLO"
        client.close()

    def test_non_2xx_raises(self, monkeypatch):
        client = _make_client()
        http = client._http_client

        monkeypatch.setattr(
            http._session, "get",
            lambda url, stream=False, timeout=None: self._fake_response(b"", status=500),
        )

        with pytest.raises(RedfishException):
            http.download("/redfish/v1/download/x.bin")
        client.close()


# ---------------------------------------------------------------------------
# Model field
# ---------------------------------------------------------------------------


def test_log_entry_additional_data_uri_alias():
    entry = LogEntry.model_validate(
        {"Id": "1", "AdditionalDataURI": "/redfish/v1/download/y.tar.gz"}
    )
    assert entry.additional_data_uri == "/redfish/v1/download/y.tar.gz"
