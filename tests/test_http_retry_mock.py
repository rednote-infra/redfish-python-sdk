"""
Unit tests for RedfishHttpClient 5xx / read-timeout retry.

Pure-stdlib unittest — no network. Run with:

    python -m unittest tests.test_http_retry_mock -v
"""
from __future__ import annotations

import unittest
from http import HTTPStatus
from typing import Any, Dict, List

import requests

from redfish_sdk import RetryPolicy
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

    def test_head_retries_and_succeeds(self) -> None:
        http = _make_http(retry_5xx=1, retry_backoff=0)
        script = _Recorder([
            _FakeResponse(HTTPStatus.SERVICE_UNAVAILABLE),
            _FakeResponse(HTTPStatus.NO_CONTENT, b""),
        ])
        http._session.head = script

        response = http._request("HEAD", "/redfish/v1/x")

        self.assertEqual(response.status_code, HTTPStatus.NO_CONTENT)
        self.assertEqual(len(script.calls), 2)

    def test_get_does_not_retry_on_4xx(self) -> None:
        http = _make_http(retry_5xx=3, retry_backoff=0)
        script = _Recorder([_FakeResponse(404, b"not found")])
        http._session.get = script
        with self.assertRaises(RedfishException):
            http.get_raw("/redfish/v1/x")
        self.assertEqual(len(script.calls), 1, "4xx must not retry")

    def test_writes_are_not_retried_after_gateway_status(self) -> None:
        for method in ("POST", "PATCH", "DELETE"):
            for status in (
                HTTPStatus.SERVICE_UNAVAILABLE,
                HTTPStatus.GATEWAY_TIMEOUT,
            ):
                with self.subTest(method=method, status=status):
                    http = _make_http(retry_5xx=2, retry_backoff=0)
                    script = _Recorder([_FakeResponse(status)])
                    setattr(http._session, method.lower(), script)

                    response = http._send(method, "/x")

                    self.assertEqual(response.status_code, status)
                    self.assertEqual(len(script.calls), 1)

    def test_idempotent_write_can_explicitly_opt_into_status_retry(self) -> None:
        http = _make_http(retry_5xx=1, retry_backoff=0)
        script = _Recorder([
            _FakeResponse(
                HTTPStatus.SERVICE_UNAVAILABLE,
                b'{"e":"unavail"}',
            ),
            _FakeResponse(HTTPStatus.NO_CONTENT, b""),
        ])
        http._session.post = script

        response = http._request(
            "POST",
            "/x",
            retry_policy=RetryPolicy.IDEMPOTENT,
        )

        self.assertEqual(response.status_code, HTTPStatus.NO_CONTENT)
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

    def test_writes_are_not_retried_after_read_timeout(self) -> None:
        for method in ("POST", "PATCH", "DELETE"):
            with self.subTest(method=method):
                http = _make_http(
                    retry_5xx=2,
                    retry_on_read_timeout=True,
                    retry_backoff=0,
                )
                script = _Recorder([requests.exceptions.ReadTimeout("slow")])
                setattr(http._session, method.lower(), script)

                with self.assertRaises(RedfishTimeoutError):
                    http._request(method, "/x")

                self.assertEqual(len(script.calls), 1)

    def test_idempotent_write_can_explicitly_opt_into_timeout_retry(self) -> None:
        http = _make_http(
            retry_5xx=1,
            retry_on_read_timeout=True,
            retry_backoff=0,
        )
        script = _Recorder([
            requests.exceptions.ReadTimeout("slow"),
            _FakeResponse(HTTPStatus.NO_CONTENT, b""),
        ])
        http._session.delete = script

        response = http._request(
            "DELETE",
            "/x",
            retry_policy=RetryPolicy.IDEMPOTENT,
        )

        self.assertEqual(response.status_code, HTTPStatus.NO_CONTENT)
        self.assertEqual(len(script.calls), 2)


class TestSuccessStatusHandling(unittest.TestCase):
    def test_complete_2xx_range_is_successful(self) -> None:
        http = _make_http()

        for status in range(HTTPStatus.OK, HTTPStatus.MULTIPLE_CHOICES):
            with self.subTest(status=status):
                http._raise_for_status(_FakeResponse(status), "/x")

    def test_found_redirect_remains_an_explicit_success(self) -> None:
        http = _make_http()

        http._raise_for_status(_FakeResponse(HTTPStatus.FOUND), "/x")

    def test_other_redirect_is_not_generic_success(self) -> None:
        http = _make_http()

        with self.assertRaises(RedfishException):
            http._raise_for_status(
                _FakeResponse(HTTPStatus.MOVED_PERMANENTLY),
                "/x",
            )


if __name__ == "__main__":
    unittest.main()
