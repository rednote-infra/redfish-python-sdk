"""
Unit tests for out-of-band diagnostic log collection + download.

Pure-stdlib (``unittest``) tests — no pytest required. Run with:

    python -m unittest tests.test_log_collect_mock -v

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

These tests never hit a real BMC; HTTP calls are stubbed on the client.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any, Dict, List, Optional

from redfish_sdk import LogEntry, RedfishClient, RedfishValidationError
from redfish_sdk.exceptions import RedfishException
from redfish_sdk.models.common import Link
from redfish_sdk.models.logs import Log
from redfish_sdk.models.managers import Manager
from redfish_sdk.models.task import Task
from redfish_sdk.managers.log_collect_strategies import (
    GenericLogCollectStrategy,
    LogCollectStrategyRegistry,
    VendorDetector,
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


def _stub_manager(client: RedfishClient) -> None:
    manager = Manager.model_construct(
        id="1",
        odata_id="/redfish/v1/Managers/1",
        log_services=Link(**{"@odata.id": "/redfish/v1/Managers/1/LogServices"}),
    )
    client._managers.get = lambda manager_id="1": manager  # type: ignore[assignment]


def _stub_log_service(client: RedfishClient, *, actions) -> None:
    log = Log.model_construct(
        id="Log1",
        odata_id="/redfish/v1/Managers/1/LogServices/Log1",
        actions=actions,
    )
    client._get_collection = (  # type: ignore[assignment]
        lambda odata_id, mc: [log] if mc is Log else []
    )


# Track VendorDetector.detect overrides so tearDown can restore the original.
_ORIGINAL_DETECT = VendorDetector.detect


def _force_vendor(vendor: str) -> None:
    VendorDetector.detect = classmethod(lambda cls, c: vendor)  # type: ignore[assignment]


def _restore_vendor() -> None:
    VendorDetector.detect = _ORIGINAL_DETECT  # type: ignore[assignment]


class _FakeResponse:
    """Minimal stand-in for requests.Response used by download tests."""

    class _Req:
        method = "GET"

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status_code = status
        self.headers: Dict[str, str] = {}
        self.request = self._Req()

    @property
    def content(self) -> bytes:
        return self._body

    def iter_content(self, chunk_size: int = 65536):
        yield self._body

    @property
    def text(self) -> str:
        return ""


class VendorRestoreMixin(unittest.TestCase):
    """Restore VendorDetector.detect after every test that may override it."""

    def tearDown(self) -> None:  # noqa: D401
        _restore_vendor()


# ---------------------------------------------------------------------------
# collect_diagnostic_data
# ---------------------------------------------------------------------------


class TestCollectDiagnosticData(VendorRestoreMixin):
    def test_generic_default_body(self) -> None:
        client = _make_client()
        _stub_manager(client)
        _stub_log_service(
            client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor("generic")

        recorder = _CallRecorder()

        def fake_post(path, model_class, body=None, raw_body=None):
            recorder.record(path=path, raw_body=raw_body)
            return Task.model_construct(
                id="42", odata_id="/redfish/v1/TaskService/Tasks/42"
            )

        client._http_client.post = fake_post  # type: ignore[assignment]

        task = client.collect_diagnostic_data()
        self.assertEqual(recorder.last["path"], COLLECT_TARGET)
        self.assertEqual(recorder.last["raw_body"], {"DiagnosticDataType": "Manager"})
        self.assertEqual(task.id, "42")
        client.close()

    def test_explicit_type_overrides_default(self) -> None:
        client = _make_client()
        _stub_manager(client)
        _stub_log_service(
            client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor("xfusion")  # default would be OEM

        recorder = _CallRecorder()

        def fake_post(path, mc, body=None, raw_body=None):
            recorder.record(raw_body=raw_body)
            return Task.model_construct(id="1")

        client._http_client.post = fake_post  # type: ignore[assignment]

        client.collect_diagnostic_data(diagnostic_data_type="Manager")
        self.assertEqual(recorder.last["raw_body"]["DiagnosticDataType"], "Manager")
        client.close()

    def test_oem_params_merged(self) -> None:
        client = _make_client()
        _stub_manager(client)
        _stub_log_service(
            client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor("generic")

        recorder = _CallRecorder()

        def fake_post(path, mc, body=None, raw_body=None):
            recorder.record(raw_body=raw_body)
            return Task.model_construct(id="1")

        client._http_client.post = fake_post  # type: ignore[assignment]

        client.collect_diagnostic_data(oem_params={"OEMDiagnosticDataType": "Full"})
        self.assertEqual(recorder.last["raw_body"]["OEMDiagnosticDataType"], "Full")
        client.close()

    def test_missing_action_raises(self) -> None:
        client = _make_client()
        _stub_manager(client)
        _stub_log_service(client, actions=None)

        with self.assertRaises(RedfishValidationError) as ctx:
            client.collect_diagnostic_data()
        self.assertIn("CollectDiagnosticData", str(ctx.exception))
        client.close()


# ---------------------------------------------------------------------------
# download_diagnostic_data
# ---------------------------------------------------------------------------


class TestDownloadDiagnosticData(VendorRestoreMixin):
    def test_from_log_entry_bytes(self) -> None:
        client = _make_client()
        entry = LogEntry.model_construct(
            id="1", additional_data_uri="/redfish/v1/download/bundle.tar.gz"
        )

        recorder = _CallRecorder()

        def fake_download(uri, output_path=None, chunk_size=65536):
            recorder.record(uri=uri, output_path=output_path)
            return b"BUNDLE"

        client._http_client.download = fake_download  # type: ignore[assignment]

        data = client.download_diagnostic_data(entry)
        self.assertEqual(data, b"BUNDLE")
        self.assertEqual(recorder.last["uri"], "/redfish/v1/download/bundle.tar.gz")
        self.assertIsNone(recorder.last["output_path"])
        client.close()

    def test_from_task_resolves_uri(self) -> None:
        client = _make_client()
        _force_vendor("generic")
        task = Task.model_construct(
            id="42", odata_id="/redfish/v1/TaskService/Tasks/42"
        )

        # Generic strategy resolves via raw task body AdditionalDataURI.
        client._http_client.get_raw = lambda path: {  # type: ignore[assignment]
            "Id": "42",
            "AdditionalDataURI": "/redfish/v1/download/42.tar.gz",
        }

        recorder = _CallRecorder()

        def fake_download(uri, output_path=None, chunk_size=65536):
            recorder.record(uri=uri, output_path=output_path)
            return "/tmp/42.tar.gz"

        client._http_client.download = fake_download  # type: ignore[assignment]

        path = client.download_diagnostic_data(task, output_path="/tmp/42.tar.gz")
        self.assertEqual(path, "/tmp/42.tar.gz")
        self.assertEqual(recorder.last["uri"], "/redfish/v1/download/42.tar.gz")
        client.close()

    def test_missing_uri_raises(self) -> None:
        client = _make_client()
        entry = LogEntry.model_construct(id="1", additional_data_uri=None)
        with self.assertRaises(RedfishValidationError) as ctx:
            client.download_diagnostic_data(entry)
        self.assertIn("download URI", str(ctx.exception))
        client.close()


# ---------------------------------------------------------------------------
# collect_and_download_diagnostic_data
# ---------------------------------------------------------------------------


class TestCollectAndDownload(VendorRestoreMixin):
    def test_end_to_end(self) -> None:
        client = _make_client()
        _stub_manager(client)
        _stub_log_service(
            client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor("generic")

        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: Task.model_construct(id="7")
        )
        completed = Task.model_construct(
            id="7",
            task_state="Completed",
            task_status="OK",
            additional_data_uri="/redfish/v1/download/7.tar.gz",
        )
        client.wait_for_task = (  # type: ignore[assignment]
            lambda task_id, poll_interval, timeout: completed
        )
        client._managers._resolve_diagnostic_download_uri = (  # type: ignore[assignment]
            lambda t: "/redfish/v1/download/7.tar.gz"
        )
        client._http_client.download = (  # type: ignore[assignment]
            lambda uri, output_path=None, chunk_size=65536: os.path.abspath(output_path)
        )

        path = client.collect_and_download_diagnostic_data("/tmp/7.tar.gz")
        self.assertEqual(path, os.path.abspath("/tmp/7.tar.gz"))
        client.close()

    def test_task_failure_raises(self) -> None:
        client = _make_client()
        _stub_manager(client)
        _stub_log_service(
            client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor("generic")

        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: Task.model_construct(id="9")
        )
        failed = Task.model_construct(
            id="9", task_state="Exception", task_status="Warning"
        )
        client.wait_for_task = (  # type: ignore[assignment]
            lambda task_id, poll_interval, timeout: failed
        )

        with self.assertRaises(RedfishException) as ctx:
            client.collect_and_download_diagnostic_data("/tmp/9.tar.gz")
        self.assertIn("did not succeed", str(ctx.exception))
        client.close()


# ---------------------------------------------------------------------------
# Strategy registry + vendor defaults
# ---------------------------------------------------------------------------


class TestStrategies(unittest.TestCase):
    def test_registered_vendors(self) -> None:
        vendors = LogCollectStrategyRegistry.registered_vendors()
        # Only vendors that differ from the DMTF default get a strategy.
        for v in ("generic", "xfusion"):
            self.assertIn(v, vendors)

    def test_standard_vendors_fall_back_to_generic(self) -> None:
        # Lenovo / Nettrix match the standard body -> generic fallback.
        for v in ("lenovo", "nettrix"):
            self.assertIsInstance(
                LogCollectStrategyRegistry.get(v), GenericLogCollectStrategy
            )

    def test_unknown_vendor_falls_back_to_generic(self) -> None:
        strategy = LogCollectStrategyRegistry.get("does-not-exist")
        self.assertIsInstance(strategy, GenericLogCollectStrategy)

    def test_generic_default_type(self) -> None:
        body = GenericLogCollectStrategy().build_body(None)
        self.assertEqual(body, {"DiagnosticDataType": "Manager"})

    def test_xfusion_oem_default(self) -> None:
        body = XFusionLogCollectStrategy().build_body(None)
        self.assertEqual(body["DiagnosticDataType"], "OEM")
        self.assertEqual(body["OEMDiagnosticDataType"], "Manager")


# ---------------------------------------------------------------------------
# RedfishHttpClient.download
# ---------------------------------------------------------------------------


class TestHttpDownload(unittest.TestCase):
    def test_bytes_mode_and_relative_uri(self) -> None:
        client = _make_client()
        http = client._http_client
        captured: Dict[str, Any] = {}

        def fake_get(url, stream=False, timeout=None):
            captured["url"] = url
            captured["stream"] = stream
            return _FakeResponse(b"DATA")

        http._session.get = fake_get  # type: ignore[assignment]

        data = http.download("/redfish/v1/download/x.bin")
        self.assertEqual(data, b"DATA")
        self.assertEqual(
            captured["url"], f"https://{http.host}/redfish/v1/download/x.bin"
        )
        self.assertTrue(captured["stream"])
        client.close()

    def test_file_mode_absolute_uri(self) -> None:
        client = _make_client()
        http = client._http_client

        http._session.get = (  # type: ignore[assignment]
            lambda url, stream=False, timeout=None: _FakeResponse(b"HELLO")
        )

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "sub", "bundle.bin")
            path = http.download("https://files.example.com/bundle.bin", out)
            self.assertEqual(path, os.path.abspath(out))
            with open(out, "rb") as fh:
                self.assertEqual(fh.read(), b"HELLO")
        client.close()

    def test_non_2xx_raises(self) -> None:
        client = _make_client()
        http = client._http_client

        http._session.get = (  # type: ignore[assignment]
            lambda url, stream=False, timeout=None: _FakeResponse(b"", status=500)
        )

        with self.assertRaises(RedfishException):
            http.download("/redfish/v1/download/x.bin")
        client.close()


# ---------------------------------------------------------------------------
# Model field
# ---------------------------------------------------------------------------


class TestLogEntryModel(unittest.TestCase):
    def test_additional_data_uri_alias(self) -> None:
        entry = LogEntry.model_validate(
            {"Id": "1", "AdditionalDataURI": "/redfish/v1/download/y.tar.gz"}
        )
        self.assertEqual(
            entry.additional_data_uri, "/redfish/v1/download/y.tar.gz"
        )


if __name__ == "__main__":
    unittest.main()
