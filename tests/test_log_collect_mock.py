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

from redfish_sdk import (
    LogCollectFailedError,
    LogEntry,
    RedfishClient,
    RedfishValidationError,
)
from redfish_sdk.exceptions import RedfishException
from redfish_sdk.models.common import Link
from redfish_sdk.models.logs import Log
from redfish_sdk.models.managers import Manager
from redfish_sdk.models.task import Message, Task
from redfish_sdk.managers.log_collect_strategies import (
    GenericLogCollectStrategy,
    InspurLogCollectStrategy,
    LogCollectStrategyRegistry,
    SmoothcomputeLogCollectStrategy,
    VendorDetector,
    XFusionLogCollectStrategy,
    ZteLogCollectStrategy,
)

# Fixed dummy credentials — these tests are fully offline (all HTTP calls are
# stubbed), so they must never depend on env vars or reach a real BMC.
MOCK_HOST = "mock-bmc-host"
MOCK_USER = "mock-user"
MOCK_PASSWORD = "mock-password"

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
        _force_vendor("generic")

        with self.assertRaises(RedfishValidationError) as ctx:
            client.collect_diagnostic_data()
        self.assertIn("collection action", str(ctx.exception))
        client.close()


# ---------------------------------------------------------------------------
# Multi-LogService resolution for CollectDiagnosticData
# ---------------------------------------------------------------------------


class TestMultiLogServiceResolution(VendorRestoreMixin):
    """Auto-selection + duplicate-id handling for collect_diagnostic_data."""

    @staticmethod
    def _stub_services(client, members, singles):
        """
        members: list[Log] returned by the collection listing.
        singles: dict[odata_id -> Log] returned by single-resource GET.
        """
        _stub_manager(client)
        client._get_collection = (  # type: ignore[assignment]
            lambda odata_id, mc: members if mc is Log else []
        )
        client._http_client.get = (  # type: ignore[assignment]
            lambda path, mc: singles[path]
        )
        _force_vendor("generic")

    def _member(self, log_id, url):
        return Log.model_construct(id=log_id, odata_id=url)

    def _single(self, log_id, url, *, supports):
        actions = (
            {"#LogService.CollectDiagnosticData": {"target": f"{url}/Actions/collect"}}
            if supports
            else None
        )
        return Log.model_construct(id=log_id, odata_id=url, actions=actions)

    def test_auto_selects_only_supported_service(self) -> None:
        client = _make_client()
        u_log = "/redfish/v1/Managers/1/LogServices/Log"
        u_audit = "/redfish/v1/Managers/1/LogServices/AuditLog"
        members = [self._member("Log", u_log), self._member("AuditLog", u_audit)]
        singles = {
            u_log: self._single("Log", u_log, supports=True),
            u_audit: self._single("AuditLog", u_audit, supports=False),
        }
        self._stub_services(client, members, singles)

        recorder = _CallRecorder()
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: (
                recorder.record(path=path) or Task.model_construct(id="1")
            )
        )

        # log_id=None but only "Log" supports the action -> auto-selected.
        client.collect_diagnostic_data()
        self.assertEqual(recorder.last["path"], f"{u_log}/Actions/collect")
        client.close()

    def test_none_supported_raises(self) -> None:
        client = _make_client()
        u_a = "/redfish/v1/Managers/1/LogServices/A"
        u_b = "/redfish/v1/Managers/1/LogServices/B"
        members = [self._member("A", u_a), self._member("B", u_b)]
        singles = {
            u_a: self._single("A", u_a, supports=False),
            u_b: self._single("B", u_b, supports=False),
        }
        self._stub_services(client, members, singles)

        with self.assertRaises(RedfishValidationError) as ctx:
            client.collect_diagnostic_data()
        self.assertIn("No log service", str(ctx.exception))
        client.close()

    def test_multiple_supported_raises(self) -> None:
        client = _make_client()
        u_a = "/redfish/v1/Managers/1/LogServices/A"
        u_b = "/redfish/v1/Managers/1/LogServices/B"
        members = [self._member("A", u_a), self._member("B", u_b)]
        singles = {
            u_a: self._single("A", u_a, supports=True),
            u_b: self._single("B", u_b, supports=True),
        }
        self._stub_services(client, members, singles)

        with self.assertRaises(RedfishValidationError) as ctx:
            client.collect_diagnostic_data()
        self.assertIn("specify log_id", str(ctx.exception))
        client.close()

    def test_duplicate_id_resolved_by_odata_id(self) -> None:
        client = _make_client()
        # Two services share id "Log"; caller passes the full @odata.id.
        u1 = "/redfish/v1/Systems/1/LogServices/Log"
        u2 = "/redfish/v1/Managers/1/LogServices/Log"
        members = [self._member("Log", u1), self._member("Log", u2)]
        # Explicit log_id path uses resolve_log_service (no single GET needed);
        # the target comes from the matched member's actions.
        members[1].actions = {
            "#LogService.CollectDiagnosticData": {"target": f"{u2}/Actions/collect"}
        }
        _stub_manager(client)
        client._get_collection = (  # type: ignore[assignment]
            lambda odata_id, mc: members if mc is Log else []
        )
        _force_vendor("generic")

        recorder = _CallRecorder()
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: (
                recorder.record(path=path) or Task.model_construct(id="1")
            )
        )

        client.collect_diagnostic_data(log_id=u2)
        self.assertEqual(recorder.last["path"], f"{u2}/Actions/collect")
        client.close()

    def test_duplicate_id_ambiguous_raises(self) -> None:
        client = _make_client()
        u1 = "/redfish/v1/Systems/1/LogServices/Log"
        u2 = "/redfish/v1/Managers/1/LogServices/Log"
        members = [self._member("Log", u1), self._member("Log", u2)]
        _stub_manager(client)
        client._get_collection = (  # type: ignore[assignment]
            lambda odata_id, mc: members if mc is Log else []
        )
        _force_vendor("generic")

        # Bare duplicate id -> ambiguous, must pass full @odata.id.
        with self.assertRaises(RedfishValidationError) as ctx:
            client.collect_diagnostic_data(log_id="Log")
        self.assertIn("full @odata.id", str(ctx.exception))
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
        self.assertIn("AdditionalDataURI", str(ctx.exception))
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
            odata_id="/redfish/v1/TaskService/Tasks/7",
            task_state="Completed",
            task_status="OK",
        )
        client.wait_for_task = (  # type: ignore[assignment]
            lambda task_id, poll_interval, timeout: completed
        )
        # Generic download resolves AdditionalDataURI from the task raw body.
        client._http_client.get_raw = (  # type: ignore[assignment]
            lambda path: {"Id": "7", "AdditionalDataURI": "/redfish/v1/download/7.tar.gz"}
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
# Reuse-of-prior-task + retry + rich failure details
# ---------------------------------------------------------------------------


class TestReusePriorTask(VendorRestoreMixin):
    """
    ``collect_and_download_diagnostic_data(reuse_existing=True)`` should
    prefer downloading the artifact of a prior collect task on the BMC
    rather than triggering a new (possibly redundant or failing) collection.
    """

    def _stub_common(self, client) -> None:
        _stub_manager(client)
        _stub_log_service(
            client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor("generic")

    def test_reuse_completed_prior_task_skips_trigger(self) -> None:
        client = _make_client()
        self._stub_common(client)

        # Strategy reports a completed prior task -> should NOT call post.
        prior = Task.model_construct(
            id="7",
            odata_id="/redfish/v1/TaskService/Tasks/7",
            task_state="Completed",
            task_status="OK",
        )
        client._managers._find_existing_collect_task = (  # type: ignore[assignment]
            lambda strategy, manager_id: prior
        )

        def unexpected_post(*a, **kw):
            raise AssertionError("collect trigger must not run when reusing")

        client._http_client.post = unexpected_post  # type: ignore[assignment]
        client._http_client.get_raw = (  # type: ignore[assignment]
            lambda path: {"Id": "7", "AdditionalDataURI": "/redfish/v1/dl/7.tgz"}
        )
        client._http_client.download = (  # type: ignore[assignment]
            lambda uri, output_path=None, chunk_size=65536: os.path.abspath(output_path)
        )

        path = client.collect_and_download_diagnostic_data("/tmp/7.tgz")
        self.assertEqual(path, os.path.abspath("/tmp/7.tgz"))
        client.close()

    def test_reuse_running_prior_task_waits_only(self) -> None:
        client = _make_client()
        self._stub_common(client)

        prior = Task.model_construct(
            id="8",
            odata_id="/redfish/v1/TaskService/Tasks/8",
            task_state="Running",
        )
        client._managers._find_existing_collect_task = (  # type: ignore[assignment]
            lambda strategy, manager_id: prior
        )

        # wait_for_task returns a completed version of the same task.
        completed = Task.model_construct(
            id="8",
            odata_id="/redfish/v1/TaskService/Tasks/8",
            task_state="Completed",
            task_status="OK",
        )
        client.wait_for_task = (  # type: ignore[assignment]
            lambda task_id, poll_interval, timeout: completed
        )
        client._http_client.get_raw = (  # type: ignore[assignment]
            lambda path: {"Id": "8", "AdditionalDataURI": "/redfish/v1/dl/8.tgz"}
        )
        client._http_client.download = (  # type: ignore[assignment]
            lambda uri, output_path=None, chunk_size=65536: os.path.abspath(output_path)
        )

        def unexpected_post(*a, **kw):
            raise AssertionError("collect trigger must not run when reusing")

        client._http_client.post = unexpected_post  # type: ignore[assignment]

        path = client.collect_and_download_diagnostic_data("/tmp/8.tgz")
        self.assertEqual(path, os.path.abspath("/tmp/8.tgz"))
        client.close()

    def test_reuse_existing_false_forces_new_trigger(self) -> None:
        client = _make_client()
        self._stub_common(client)

        # Even if a prior task exists, reuse_existing=False must trigger fresh.
        prior = Task.model_construct(
            id="99", odata_id="/redfish/v1/TaskService/Tasks/99",
            task_state="Completed", task_status="OK",
        )
        client._managers._find_existing_collect_task = (  # type: ignore[assignment]
            lambda strategy, manager_id: prior
        )

        triggered = []
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: (
                triggered.append(path)
                or Task.model_construct(id="new-1")
            )
        )
        client.wait_for_task = (  # type: ignore[assignment]
            lambda task_id, poll_interval, timeout: Task.model_construct(
                id="new-1",
                odata_id="/redfish/v1/TaskService/Tasks/new-1",
                task_state="Completed",
                task_status="OK",
            )
        )
        client._http_client.get_raw = (  # type: ignore[assignment]
            lambda path: {"Id": "new-1", "AdditionalDataURI": "/x"}
        )
        client._http_client.download = (  # type: ignore[assignment]
            lambda uri, output_path=None, chunk_size=65536: os.path.abspath(output_path)
        )

        client.collect_and_download_diagnostic_data(
            "/tmp/x.tgz", reuse_existing=False
        )
        self.assertEqual(len(triggered), 1, "trigger must run when reuse disabled")
        client.close()


class TestRetryOnFailure(VendorRestoreMixin):
    """
    ``collect_and_download_diagnostic_data(max_retries=N)`` should retry the
    trigger-and-wait sequence on :class:`LogCollectFailedError` up to N extra
    times, and give up (raising the last error) otherwise.
    """

    def _stub_common(self, client) -> None:
        _stub_manager(client)
        _stub_log_service(
            client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor("generic")
        # Disable reuse and neutralise sleep.
        client._managers._find_existing_collect_task = (  # type: ignore[assignment]
            lambda strategy, manager_id: None
        )

    def test_no_retry_by_default(self) -> None:
        client = _make_client()
        self._stub_common(client)
        attempts = []
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: (
                attempts.append(path)
                or Task.model_construct(id=str(len(attempts)))
            )
        )
        client.wait_for_task = (  # type: ignore[assignment]
            lambda task_id, poll_interval, timeout: Task.model_construct(
                id=task_id, task_state="Exception", task_status="Critical"
            )
        )
        with self.assertRaises(LogCollectFailedError):
            client.collect_and_download_diagnostic_data("/tmp/x.tgz")
        self.assertEqual(len(attempts), 1, "must not retry by default")
        client.close()

    def test_retry_succeeds_on_second_attempt(self) -> None:
        client = _make_client()
        self._stub_common(client)
        attempts = []
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: (
                attempts.append(path)
                or Task.model_construct(
                    id=str(len(attempts)),
                    odata_id=f"/redfish/v1/TaskService/Tasks/{len(attempts)}",
                )
            )
        )

        def fake_wait(task_id, poll_interval, timeout):
            # First attempt fails, second succeeds.
            if task_id == "1":
                return Task.model_construct(
                    id="1", task_state="Exception", task_status="Warning"
                )
            return Task.model_construct(
                id=task_id,
                odata_id=f"/redfish/v1/TaskService/Tasks/{task_id}",
                task_state="Completed",
                task_status="OK",
            )

        client.wait_for_task = fake_wait  # type: ignore[assignment]
        client._http_client.get_raw = (  # type: ignore[assignment]
            lambda path: {"Id": "2", "AdditionalDataURI": "/dl/2"}
        )
        client._http_client.download = (  # type: ignore[assignment]
            lambda uri, output_path=None, chunk_size=65536: os.path.abspath(output_path)
        )

        path = client.collect_and_download_diagnostic_data(
            "/tmp/ok.tgz", max_retries=1, retry_backoff=0
        )
        self.assertEqual(path, os.path.abspath("/tmp/ok.tgz"))
        self.assertEqual(len(attempts), 2)
        client.close()

    def test_retry_exhausted_raises_last_error(self) -> None:
        client = _make_client()
        self._stub_common(client)
        attempts = []
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: (
                attempts.append(path)
                or Task.model_construct(id=str(len(attempts)))
            )
        )
        client.wait_for_task = (  # type: ignore[assignment]
            lambda task_id, poll_interval, timeout: Task.model_construct(
                id=task_id, task_state="Exception", task_status="Critical",
                messages=[Message.model_construct(
                    message_id="Base.1.13.0.InternalError",
                    message="Internal service error",
                )],
            )
        )

        with self.assertRaises(LogCollectFailedError) as ctx:
            client.collect_and_download_diagnostic_data(
                "/tmp/x.tgz", max_retries=2, retry_backoff=0
            )
        # 1 initial + 2 retries = 3 attempts.
        self.assertEqual(len(attempts), 3)
        # Last error carries detailed BMC context.
        self.assertEqual(ctx.exception.task_state, "Exception")
        self.assertEqual(ctx.exception.task_status, "Critical")
        self.assertTrue(
            any("InternalError" in (m.get("MessageId") or "")
                for m in ctx.exception.messages)
        )
        client.close()


class TestFailureDetails(VendorRestoreMixin):
    """LogCollectFailedError must expose full BMC diagnostic context."""

    def test_generic_failure_populates_messages(self) -> None:
        client = _make_client()
        _stub_manager(client)
        _stub_log_service(
            client,
            actions={"#LogService.CollectDiagnosticData": {"target": COLLECT_TARGET}},
        )
        _force_vendor("generic")
        client._managers._find_existing_collect_task = (  # type: ignore[assignment]
            lambda strategy, manager_id: None
        )
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: Task.model_construct(id="42")
        )
        client.wait_for_task = (  # type: ignore[assignment]
            lambda task_id, poll_interval, timeout: Task.model_construct(
                id="42",
                task_state="Cancelled",
                task_status="Warning",
                messages=[
                    Message.model_construct(
                        message_id="TaskEvent.1.0.3.TaskStarted",
                        message="Task started",
                    ),
                    Message.model_construct(
                        message_id="TaskEvent.1.0.3.TaskAborted",
                        message="Task completed with errors",
                        severity="Warning",
                    ),
                    Message.model_construct(
                        message_id="Base.1.13.0.InternalError",
                        message="The request failed due to an internal service error.",
                        resolution="Retry later.",
                    ),
                ],
            )
        )
        with self.assertRaises(LogCollectFailedError) as ctx:
            client.collect_and_download_diagnostic_data("/tmp/x.tgz")
        e = ctx.exception
        self.assertEqual(e.task_id, "42")
        self.assertEqual(e.task_state, "Cancelled")
        self.assertEqual(e.task_status, "Warning")
        self.assertEqual(len(e.messages), 3)
        # The one-line summary highlights the tail messages.
        self.assertIn("InternalError", str(e))
        client.close()


class TestFindExistingTaskDiscovery(VendorRestoreMixin):
    """base find_existing_task (TaskService heuristic) + ZTE override."""

    def test_generic_finds_task_by_payload_target(self) -> None:
        client = _make_client()
        _force_vendor("generic")
        strategy = client._managers  # placeholder just to satisfy signature

        from redfish_sdk.managers.log_collect_strategies import (
            GenericLogCollectStrategy,
        )
        strategy = GenericLogCollectStrategy()

        # get_tasks returns two members; only one is a collection task.
        client.get_tasks = (  # type: ignore[assignment]
            lambda: [
                Task.model_construct(id="1", odata_id="/redfish/v1/TaskService/Tasks/1"),
                Task.model_construct(id="2", odata_id="/redfish/v1/TaskService/Tasks/2"),
            ]
        )

        def fake_get_raw(path):
            if path.endswith("/Tasks/1"):
                return {"Id": "1", "TaskState": "Completed", "StartTime": "2026-01-01"}
            if path.endswith("/Tasks/2"):
                return {
                    "Id": "2",
                    "TaskState": "Running",
                    "StartTime": "2026-02-01",
                    "Payload": {
                        "TargetUri": (
                            "/redfish/v1/Systems/1/LogServices/Log/Actions/"
                            "LogService.CollectDiagnosticData"
                        )
                    },
                }
            raise AssertionError(f"unexpected get_raw: {path}")

        client._http_client.get_raw = fake_get_raw  # type: ignore[assignment]

        found = strategy.find_existing_task(client, "/x", manager_id="1")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, "2")
        client.close()

    def test_generic_returns_none_when_no_collect_task(self) -> None:
        client = _make_client()
        _force_vendor("generic")
        from redfish_sdk.managers.log_collect_strategies import (
            GenericLogCollectStrategy,
        )
        strategy = GenericLogCollectStrategy()

        client.get_tasks = lambda: []  # type: ignore[assignment]
        self.assertIsNone(
            strategy.find_existing_task(client, "/x", manager_id="1")
        )
        client.close()

    def test_zte_reuses_completed_progress(self) -> None:
        client = _make_client()
        _force_vendor("zte")
        from redfish_sdk.managers.log_collect_strategies import ZteLogCollectStrategy

        strategy = ZteLogCollectStrategy()

        def fake_get_raw(path):
            if path == "/x/LogServices":
                return {
                    "@odata.id": "/x/LogServices",
                    "Actions": {"Oem": {"#LogServices.Dump": {
                        "target": "/x/LogServices/Actions/LogServices.Dump"
                    }}},
                }
            if path.endswith("Dump/Progress"):
                return {
                    "State": "STATE_COMPLETED",
                    "Percentage": "100",
                    "TarPath": "/tmp/logs/ok.tar.gz",
                    "Type": "AllLogs",
                }
            raise AssertionError(f"unexpected: {path}")

        client._http_client.get_raw = fake_get_raw  # type: ignore[assignment]
        found = strategy.find_existing_task(client, "/x/LogServices", "Self")
        self.assertIsNotNone(found)
        self.assertEqual(found.task_state, "Completed")
        self.assertEqual(getattr(found, "_zte_tar_path"), "/tmp/logs/ok.tar.gz")
        client.close()

    def test_zte_returns_none_when_progress_failed(self) -> None:
        client = _make_client()
        _force_vendor("zte")
        from redfish_sdk.managers.log_collect_strategies import ZteLogCollectStrategy

        strategy = ZteLogCollectStrategy()

        def fake_get_raw(path):
            if path == "/x/LogServices":
                return {
                    "Actions": {"Oem": {"#LogServices.Dump": {
                        "target": "/x/LogServices/Actions/LogServices.Dump"
                    }}},
                }
            if path.endswith("Dump/Progress"):
                return {"State": "STATE_FAILED", "TarPath": ".tar.gz"}
            raise AssertionError(f"unexpected: {path}")

        client._http_client.get_raw = fake_get_raw  # type: ignore[assignment]
        self.assertIsNone(
            strategy.find_existing_task(client, "/x/LogServices", "Self")
        )
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

    def test_inspur_registered(self) -> None:
        self.assertIsInstance(
            LogCollectStrategyRegistry.get("inspur"), InspurLogCollectStrategy
        )

    def test_zte_registered(self) -> None:
        self.assertIsInstance(
            LogCollectStrategyRegistry.get("zte"), ZteLogCollectStrategy
        )

    def test_smoothcompute_registered(self) -> None:
        self.assertIsInstance(
            LogCollectStrategyRegistry.get("smoothcompute"),
            SmoothcomputeLogCollectStrategy,
        )


# ---------------------------------------------------------------------------
# Inspur (浪潮) collection-level CollectAllLog / DownloadAllLog OEM flow
# ---------------------------------------------------------------------------


class TestInspurStrategy(VendorRestoreMixin):
    """Verify Inspur uses the collection-level OEM action pair."""

    _COLLECTION = "/redfish/v1/Managers/1/LogServices"
    _COLLECT = f"{_COLLECTION}/Actions/Oem/Public/CollectAllLog"
    _DOWNLOAD = f"{_COLLECTION}/Actions/Oem/Public/DownloadAllLog"

    def _stub_collection_actions(self, client) -> None:
        client._http_client.get_raw = lambda path: {  # type: ignore[assignment]
            "@odata.id": self._COLLECTION,
            "Actions": {
                "#LogService.CollectAllLog": {"target": self._COLLECT},
                "#LogService.DownloadAllLog": {"target": self._DOWNLOAD},
            },
        }

    def test_collect_uses_collection_action_and_empty_body(self) -> None:
        client = _make_client()
        _stub_manager(client)
        self._stub_collection_actions(client)
        _force_vendor("inspur")

        recorder = _CallRecorder()
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: (
                recorder.record(path=path, raw_body=raw_body)
                or Task.model_construct(id="0")
            )
        )

        task = client.collect_diagnostic_data()
        self.assertEqual(recorder.last["path"], self._COLLECT)
        self.assertEqual(recorder.last["raw_body"], {})  # empty body
        self.assertEqual(task.id, "0")
        client.close()

    def test_download_uses_post_action(self) -> None:
        client = _make_client()
        self._stub_collection_actions(client)
        _force_vendor("inspur")

        recorder = _CallRecorder()
        client._http_client.download_via_post = (  # type: ignore[assignment]
            lambda path, output_path=None, raw_body=None: (
                recorder.record(path=path, output_path=output_path)
                or "/tmp/out/dump_x.tar.gz"
            )
        )
        # Manager collection path hint used by the strategy.
        client._get_managers_collection_odata_id = (  # type: ignore[assignment]
            lambda: "/redfish/v1/Managers"
        )

        task = Task.model_construct(id="0", odata_id="/redfish/v1/TaskService/Tasks/0")
        path = client.download_diagnostic_data(task, output_path="/tmp/out/")
        self.assertEqual(path, "/tmp/out/dump_x.tar.gz")
        self.assertEqual(recorder.last["path"], self._DOWNLOAD)
        client.close()


# ---------------------------------------------------------------------------
# smoothcompute (顺算) DiagnosticService.CollectBlackBox / ExportBlackBox
# ---------------------------------------------------------------------------


class TestSmoothcomputeStrategy(VendorRestoreMixin):
    """
    Verify smoothcompute uses the OEM DiagnosticService actions and reuses
    the standard TaskService wait flow.
    """

    _LOGSVCS = "/redfish/v1/Managers/1/LogServices"
    _MANAGER = "/redfish/v1/Managers/1"
    _DIAG = f"{_MANAGER}/DiagnosticService"
    _COLLECT = f"{_DIAG}/Actions/DiagnosticService.CollectBlackBox"
    _EXPORT = f"{_DIAG}/Actions/DiagnosticService.ExportBlackBox"

    def _stub_diag_service(self, client) -> None:
        """Stub the DiagnosticService resource so both actions are visible."""
        def fake_get_raw(path):
            if path == self._DIAG:
                return {
                    "@odata.id": self._DIAG,
                    "Actions": {
                        "#DiagnosticService.CollectBlackInfo": {"target": self._COLLECT},
                        "#DiagnosticService.DownloadBlackInfo": {"target": self._EXPORT},
                    },
                }
            if path == "/redfish/v1/Managers":
                return {"Members": [{"@odata.id": self._MANAGER}]}
            raise AssertionError(f"unexpected get_raw: {path}")

        client._http_client.get_raw = fake_get_raw  # type: ignore[assignment]
        client._get_managers_collection_odata_id = (  # type: ignore[assignment]
            lambda: "/redfish/v1/Managers"
        )

    def test_collect_posts_diagnostic_action_with_empty_body(self) -> None:
        client = _make_client()
        _stub_manager(client)
        self._stub_diag_service(client)
        _force_vendor("smoothcompute")

        recorder = _CallRecorder()
        client._http_client.post = (  # type: ignore[assignment]
            lambda path, mc, body=None, raw_body=None: (
                recorder.record(path=path, raw_body=raw_body)
                or Task.model_construct(
                    id="CollectBlackBox",
                    odata_id="/redfish/v1/TaskService/Tasks/1",
                    task_state="Running",
                )
            )
        )

        task = client.collect_diagnostic_data()
        self.assertEqual(recorder.last["path"], self._COLLECT)
        self.assertEqual(recorder.last["raw_body"], {})
        # Task with a human-friendly Id ("CollectBlackBox") but a numeric
        # @odata.id — the base wait_until_ready should prefer the URL tail.
        self.assertEqual(task.id, "CollectBlackBox")
        client.close()

    def test_download_uses_export_action(self) -> None:
        client = _make_client()
        self._stub_diag_service(client)
        _force_vendor("smoothcompute")

        recorder = _CallRecorder()
        client._http_client.download_via_post = (  # type: ignore[assignment]
            lambda path, output_path=None, raw_body=None: (
                recorder.record(path=path, output_path=output_path)
                or "/tmp/out/6415_X2_SN_ts.zip.gz"
            )
        )

        task = Task.model_construct(
            id="CollectBlackBox",
            odata_id="/redfish/v1/TaskService/Tasks/1",
            task_state="Completed",
        )
        path = client.download_diagnostic_data(task, output_path="/tmp/out/")
        self.assertEqual(path, "/tmp/out/6415_X2_SN_ts.zip.gz")
        self.assertEqual(recorder.last["path"], self._EXPORT)
        client.close()


# ---------------------------------------------------------------------------
# Base.wait_until_ready: task_id resolution from @odata.id
# ---------------------------------------------------------------------------


class TestWaitUntilReadyTaskIdResolution(VendorRestoreMixin):
    """
    smoothcompute-style BMCs put a human-friendly name into ``Task.Id`` and
    the real TaskService key in ``@odata.id``. wait_until_ready must resolve
    the id from the URL, not blindly use ``task.id``.
    """

    def test_prefers_odata_id_tail_over_task_id(self) -> None:
        strategy = GenericLogCollectStrategy()

        # Mimic a smoothcompute trigger response.
        task = Task.model_construct(
            id="CollectBlackBox",
            odata_id="/redfish/v1/TaskService/Tasks/1",
        )

        client = _make_client()
        captured = {}

        def fake_wait(task_id, poll_interval, timeout):
            captured["task_id"] = task_id
            return Task.model_construct(
                id=task_id, task_state="Completed", task_status="OK",
            )

        client.wait_for_task = fake_wait  # type: ignore[assignment]

        strategy.wait_until_ready(client, task, poll_interval=1, timeout=10)
        # Must have used the numeric tail, not the name.
        self.assertEqual(captured["task_id"], "1")
        client.close()

    def test_falls_back_to_task_id_when_no_odata_id(self) -> None:
        strategy = GenericLogCollectStrategy()
        task = Task.model_construct(id="42", odata_id=None)

        client = _make_client()
        captured = {}

        def fake_wait(task_id, poll_interval, timeout):
            captured["task_id"] = task_id
            return Task.model_construct(
                id=task_id, task_state="Completed", task_status="OK",
            )

        client.wait_for_task = fake_wait  # type: ignore[assignment]

        strategy.wait_until_ready(client, task, poll_interval=1, timeout=10)
        self.assertEqual(captured["task_id"], "42")
        client.close()


# ---------------------------------------------------------------------------
# Task model: normalise non-list Messages
# ---------------------------------------------------------------------------


class TestTaskMessagesNormalisation(unittest.TestCase):
    def test_single_message_dict_wrapped_as_list(self) -> None:
        # smoothcompute returns Messages as a single object, not a list.
        raw = {
            "Id": "1",
            "TaskState": "Completed",
            "Messages": {
                "@odata.type": "/redfish/v1/$metadata#Message.v1_1_1.Message",
                "MessageId": "TaskEvent.1.0.0.TaskCompletedOK",
                "Message": "The task is complete.",
            },
        }
        task = Task.model_validate(raw)
        self.assertIsInstance(task.messages, list)
        self.assertEqual(len(task.messages), 1)
        self.assertEqual(
            task.messages[0].message_id, "TaskEvent.1.0.0.TaskCompletedOK"
        )

    def test_list_messages_unchanged(self) -> None:
        raw = {
            "Id": "1",
            "Messages": [
                {"MessageId": "A"},
                {"MessageId": "B"},
            ],
        }
        task = Task.model_validate(raw)
        self.assertEqual(len(task.messages), 2)


# ---------------------------------------------------------------------------
# ZTE (中兴) Dump / Dump/Progress / GeneralDownload OEM flow
# ---------------------------------------------------------------------------


class TestZteStrategy(VendorRestoreMixin):
    """
    Verify ZTE uses the OEM Dump action + bespoke progress endpoint +
    Manager.GeneralDownload for the artifact.
    """

    _LOGSVCS = "/redfish/v1/Managers/Self/LogServices"
    _DUMP = f"{_LOGSVCS}/Actions/LogServices.Dump"
    _PROGRESS = f"{_DUMP}/Progress"
    _MANAGER = "/redfish/v1/Managers/Self"
    _GD = f"{_MANAGER}/Actions/Manager.GeneralDownload"

    def _stub_manager(self, client) -> None:
        """Stub a ZTE-style Manager (id='Self') with a LogServices link."""
        manager = Manager.model_construct(
            id="Self",
            odata_id=self._MANAGER,
            log_services=Link(**{"@odata.id": self._LOGSVCS}),
        )
        client._managers.get = lambda manager_id="Self": manager  # type: ignore[assignment]

    def _stub_get_raw(self, client, *, progress_state="STATE_COMPLETED",
                     tar_path="/tmp/logs/xxx.tar.gz"):
        """Stub get_raw for: LogServices collection, Dump/Progress, Managers
        collection, and Manager resource (for GeneralDownload discovery)."""
        managers_col = "/redfish/v1/Managers"

        def fake(path):
            if path == self._LOGSVCS:
                return {
                    "@odata.id": self._LOGSVCS,
                    "Actions": {"Oem": {"#LogServices.Dump": {"target": self._DUMP}}},
                }
            if path == self._PROGRESS:
                return {
                    "State": progress_state,
                    "Percentage": "100" if "COMPLETED" in progress_state else "50",
                    "TarPath": tar_path,
                    "Type": "AllLogs",
                    "Message": "",
                }
            if path == managers_col:
                return {"Members": [{"@odata.id": self._MANAGER}]}
            if path == self._MANAGER:
                return {
                    "@odata.id": self._MANAGER,
                    "Actions": {"#Manager.GeneralDownload": {"target": self._GD}},
                }
            raise AssertionError(f"unexpected get_raw path: {path}")

        client._http_client.get_raw = fake  # type: ignore[assignment]
        client._get_managers_collection_odata_id = (  # type: ignore[assignment]
            lambda: managers_col
        )

    def test_trigger_posts_dump_with_default_type(self) -> None:
        client = _make_client()
        self._stub_manager(client)
        self._stub_get_raw(client)
        _force_vendor("zte")

        recorder = _CallRecorder()

        def fake_post(path, mc, body=None, raw_body=None):
            recorder.record(path=path, raw_body=raw_body)
            # Dump returns a plain success message, not a Task; the strategy
            # ignores the parsed body.
            return mc.model_construct()

        client._http_client.post = fake_post  # type: ignore[assignment]

        task = client.collect_diagnostic_data(manager_id="Self")
        self.assertEqual(recorder.last["path"], self._DUMP)
        self.assertEqual(recorder.last["raw_body"], {"Type": "AllLogs"})
        # Synthetic task should carry progress URL context.
        self.assertEqual(getattr(task, "_zte_progress_url"), self._PROGRESS)
        client.close()

    def test_wait_until_ready_polls_progress_endpoint(self) -> None:
        client = _make_client()
        self._stub_get_raw(client, progress_state="STATE_COMPLETED",
                          tar_path="/tmp/logs/ok.tar.gz")
        strategy = ZteLogCollectStrategy()

        task = Task.model_construct(
            id="zte-dump",
            _zte_progress_url=self._PROGRESS,
            _zte_manager_id="Self",
        )
        finished = strategy.wait_until_ready(client, task, poll_interval=1, timeout=5)
        self.assertEqual(finished.task_state, "Completed")
        self.assertEqual(getattr(finished, "_zte_tar_path"), "/tmp/logs/ok.tar.gz")
        client.close()

    def test_wait_until_ready_raises_on_failed_state(self) -> None:
        client = _make_client()
        # First poll already terminal-failed after one non-zero elapsed cycle.
        self._stub_get_raw(client, progress_state="STATE_FAILED")
        strategy = ZteLogCollectStrategy()

        task = Task.model_construct(
            id="zte-dump", _zte_progress_url=self._PROGRESS
        )
        # iteration 0 treats STATE_FAILED as stale; the second read (at
        # elapsed=1s) is terminal and raises.
        with self.assertRaises(RedfishException) as ctx:
            strategy.wait_until_ready(client, task, poll_interval=1, timeout=3)
        self.assertIn("ZTE diagnostic collection", str(ctx.exception))
        client.close()

    def test_download_uses_general_download_with_tar_path(self) -> None:
        client = _make_client()
        self._stub_get_raw(client)
        _force_vendor("zte")

        recorder = _CallRecorder()
        client._http_client.download_via_post = (  # type: ignore[assignment]
            lambda path, output_path=None, raw_body=None: (
                recorder.record(path=path, raw_body=raw_body,
                                output_path=output_path)
                or "/tmp/out/ok.tar.gz"
            )
        )

        # Task carrying the resolved TarPath from a completed wait.
        task = Task.model_construct(
            id="zte-dump",
            _zte_progress_url=self._PROGRESS,
            _zte_manager_id="Self",
            _zte_tar_path="/tmp/logs/ok.tar.gz",
        )
        path = client.download_diagnostic_data(task, output_path="/tmp/out/")
        self.assertEqual(path, "/tmp/out/ok.tar.gz")
        self.assertEqual(recorder.last["path"], self._GD)
        self.assertEqual(recorder.last["raw_body"], {"Path": "/tmp/logs/ok.tar.gz"})
        client.close()


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

    def test_download_via_post_uses_content_disposition_filename(self) -> None:
        client = _make_client()
        http = client._http_client

        resp = _FakeResponse(b"\x1f\x8bDATA")
        resp.headers = {
            "Content-Disposition": 'attachment; filename="dump_ABC_20260902.tar.gz"'
        }
        http._session.post = (  # type: ignore[assignment]
            lambda url, json=None, stream=False, timeout=None: resp
        )

        with tempfile.TemporaryDirectory() as tmp:
            # Pass a directory -> filename taken from Content-Disposition.
            path = http.download_via_post(
                "/redfish/v1/.../DownloadAllLog", output_path=tmp + os.sep
            )
            self.assertEqual(
                os.path.basename(path), "dump_ABC_20260902.tar.gz"
            )
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), b"\x1f\x8bDATA")
        client.close()

    def test_download_via_post_bytes_mode(self) -> None:
        client = _make_client()
        http = client._http_client
        http._session.post = (  # type: ignore[assignment]
            lambda url, json=None, stream=False, timeout=None: _FakeResponse(b"BIN")
        )
        data = http.download_via_post("/x/Download", output_path=None)
        self.assertEqual(data, b"BIN")
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


# ---------------------------------------------------------------------------
# VendorDetector: smoothcompute recognition
# ---------------------------------------------------------------------------


class TestVendorDetectSmoothcompute(unittest.TestCase):
    """The Vendor / Manufacturer keyword table must recognise smoothcompute."""

    def test_smoothcompute_in_keyword_table(self) -> None:
        from redfish_sdk.managers.update_strategies.vendor_detect import (
            _VENDOR_KEYWORDS,
        )
        self.assertIn("smoothcompute", _VENDOR_KEYWORDS)
        self.assertIn("smoothcompute", _VENDOR_KEYWORDS["smoothcompute"])


if __name__ == "__main__":
    unittest.main()
