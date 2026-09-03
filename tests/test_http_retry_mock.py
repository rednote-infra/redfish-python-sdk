"""
Unit tests for RedfishHttpClient 5xx / read-timeout retry.

Pure-stdlib unittest — no network. Run with:

    python -m unittest tests.test_http_retry_mock -v
"""
from __future__ import annotations

import unittest
from typing import Any, Dict, List

import requests

from redfish_sdk.exceptions import RedfishException, RedfishTimeoutError
from redfish_sdk.http_client import RedfishHttpClient


class _FakeResponse:
    """Minimal drop-in for requests.Response used by http_client tests."""

    class _Req:
        method = "GET"

    def __init__(self, status: int, body: bytes = b"{}", headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.request = self._Req()

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self):
        import json
        return json.loads(self.text or "{}")

    @property
    def content(self) -> bytes:
        return self._body


def _make_http(**kwargs) -> RedfishHttpClient:
    return RedfishHttpClient(
        host="mock-bmc-host",
        username="u",
        password="p",
        verify_ssl=False,
        connect_timeout=1,
        read_timeout=1,
        **kwargs,
    )


class _Recorder:
    """Records session-call args and dispenses scripted responses / errors."""

    def __init__(self, script: List[Any]) -> None:
        self.script = list(script)
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.script:
            raise AssertionError("script exhausted")
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


# ---------------------------------------------------------------------------
# Default (no retry) behaviour is preserved
# ---------------------------------------------------------------------------


class TestNoRetryByDefault(unittest.TestCase):
    def test_5xx_not_retried_without_flag(self) -> None:
        http = _make_http()
        script = _Recorder([_FakeResponse(500, b'{"error":"boom"}')])
        http._session.get = script
        with self.assertRaises(RedfishException) as ctx:
            http.get_raw("/redfish/v1/x")
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(len(script.calls), 1, "must not retry by default")

    def test_read_timeout_not_retried_without_flag(self) -> None:
        http = _make_http()
        script = _Recorder([requests.exceptions.ReadTimeout("bmc slow")])
        http._session.get = script
        with self.assertRaises(RedfishTimeoutError):
            http.get_raw("/redfish/v1/x")
        self.assertEqual(len(script.calls), 1)


# ---------------------------------------------------------------------------
# retry_5xx behaviour
# ---------------------------------------------------------------------------


class TestRetry5xx(unittest.TestCase):
    def test_get_retries_and_succeeds(self) -> None:
        http = _make_http(retry_5xx=2, retry_backoff=0)
        script = _Recorder([
            _FakeResponse(500, b'{"error":"first"}'),
            _FakeResponse(503, b'{"error":"second"}'),
            _FakeResponse(200, b'{"ok":true}'),
        ])
        http._session.get = script
        data = http.get_raw("/redfish/v1/x")
        self.assertEqual(data, {"ok": True})
        self.assertEqual(len(script.calls), 3)

    def test_get_gives_up_after_attempts_exhausted(self) -> None:
        http = _make_http(retry_5xx=2, retry_backoff=0)
        script = _Recorder([
            _FakeResponse(500, b'{"error":"a"}'),
            _FakeResponse(500, b'{"error":"b"}'),
            _FakeResponse(500, b'{"error":"c"}'),
        ])
        http._session.get = script
        with self.assertRaises(RedfishException) as ctx:
            http.get_raw("/redfish/v1/x")
        self.assertEqual(ctx.exception.status_code, 500)
        # 1 initial + 2 retries = 3 total attempts.
        self.assertEqual(len(script.calls), 3)

    def test_get_does_not_retry_on_4xx(self) -> None:
        http = _make_http(retry_5xx=3, retry_backoff=0)
        script = _Recorder([_FakeResponse(404, b"not found")])
        http._session.get = script
        with self.assertRaises(RedfishException):
            http.get_raw("/redfish/v1/x")
        self.assertEqual(len(script.calls), 1, "4xx must not retry")

    def test_post_retries_only_on_503_504(self) -> None:
        # 500 on a write is NOT retried (write may have partially applied).
        http = _make_http(retry_5xx=3, retry_backoff=0)
        script = _Recorder([_FakeResponse(500, b'{"e":"internal"}')])
        http._session.post = script
        with self.assertRaises(RedfishException) as ctx:
            http.post_raw("/x", body={})
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(len(script.calls), 1, "POST must NOT retry on 500")

    def test_post_retries_on_503(self) -> None:
        http = _make_http(retry_5xx=2, retry_backoff=0)
        script = _Recorder([
            _FakeResponse(503, b'{"e":"unavail"}'),
            _FakeResponse(200, b'{"ok":true}'),
        ])
        http._session.post = script
        resp = http.post_raw("/x", body={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(script.calls), 2)


# ---------------------------------------------------------------------------
# retry_on_read_timeout
# ---------------------------------------------------------------------------


class TestRetryOnReadTimeout(unittest.TestCase):
    def test_get_retries_on_read_timeout_then_succeeds(self) -> None:
        http = _make_http(
            retry_5xx=0, retry_on_read_timeout=True, retry_backoff=0
        )
        # ReadTimeout counts as a retry attempt independent of retry_5xx;
        # attempts still bounded by max(retry_5xx, 0) + 1 = 1 by default.
        # So allow one extra attempt via retry_5xx=1.
        http.retry_5xx = 1
        script = _Recorder([
            requests.exceptions.ReadTimeout("slow-1"),
            _FakeResponse(200, b'{"ok":true}'),
        ])
        http._session.get = script
        data = http.get_raw("/redfish/v1/x")
        self.assertEqual(data, {"ok": True})
        self.assertEqual(len(script.calls), 2)

    def test_get_read_timeout_gives_up(self) -> None:
        http = _make_http(
            retry_5xx=2, retry_on_read_timeout=True, retry_backoff=0
        )
        script = _Recorder([
            requests.exceptions.ReadTimeout("a"),
            requests.exceptions.ReadTimeout("b"),
            requests.exceptions.ReadTimeout("c"),
        ])
        http._session.get = script
        with self.assertRaises(RedfishTimeoutError):
            http.get_raw("/redfish/v1/x")
        self.assertEqual(len(script.calls), 3)


if __name__ == "__main__":
    unittest.main()
