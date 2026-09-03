"""
Unit tests for RedfishConnectionError / RedfishTimeoutError diagnostic hints.

Pure-stdlib unittest — no network, no pytest. Run with:

    python -m unittest tests.test_exception_hints_mock -v
"""
from __future__ import annotations

import unittest

from redfish_sdk.exceptions import (
    RedfishConnectionError,
    RedfishTimeoutError,
)


# Fixed dummy host — tests never open a real socket; string is only used
# to fabricate exception payloads and assert the classifier's output.
HOST = "mock-bmc-host"


class TestConnectionErrorClassification(unittest.TestCase):
    """Ensure ``cause`` is classified and a targeted hint is emitted."""

    def test_connection_refused_hint(self) -> None:
        cause = ConnectionRefusedError(61, "Connection refused")
        exc = RedfishConnectionError(HOST, cause)
        self.assertEqual(exc.reason, "refused")
        msg = str(exc)
        # Categorised as refused -> hint should call out port / Redfish service.
        self.assertIn("no service is listening", msg)
        self.assertIn(HOST, msg)
        self.assertIn("BMC address", msg)

    def test_urllib3_style_refused_message(self) -> None:
        # requests/urllib3 wraps the OS error into a longer string —
        # classification must still work on the stringified form.
        class _Fake(Exception):
            def __init__(self):
                super().__init__(
                    "HTTPSConnectionPool(host='mock-bmc-host', port=443): "
                    "Max retries exceeded with url: /redfish/v1/ "
                    "(Caused by NewConnectionError('...: Failed to establish "
                    "a new connection: [Errno 61] Connection refused'))"
                )

        exc = RedfishConnectionError(HOST, _Fake())
        self.assertEqual(exc.reason, "refused")
        self.assertIn("no service is listening", str(exc))

    def test_no_route_to_host_hint(self) -> None:
        cause = OSError(65, "No route to host")
        exc = RedfishConnectionError(HOST, cause)
        self.assertEqual(exc.reason, "unreachable")
        self.assertIn("not routable", str(exc))

    def test_dns_failure_hint(self) -> None:
        cause = OSError(-2, "Name or service not known")
        exc = RedfishConnectionError("bad-host.local", cause)
        self.assertEqual(exc.reason, "dns")
        self.assertIn("resolve host name", str(exc))

    def test_tls_failure_hint(self) -> None:
        class _SslLike(Exception):
            pass

        cause = _SslLike("SSL: WRONG_VERSION_NUMBER wrong version number")
        exc = RedfishConnectionError(HOST, cause)
        self.assertEqual(exc.reason, "tls")
        self.assertIn("TLS/SSL handshake", str(exc))
        self.assertIn("verify_ssl", str(exc))

    def test_unknown_cause_falls_back_to_generic_hint(self) -> None:
        exc = RedfishConnectionError(HOST, RuntimeError("mystery"))
        self.assertEqual(exc.reason, "other")
        self.assertIn("Verify basic connectivity", str(exc))

    def test_none_cause_is_other(self) -> None:
        exc = RedfishConnectionError(HOST, None)
        self.assertEqual(exc.reason, "other")

    def test_exposes_host_and_cause_attributes(self) -> None:
        cause = ConnectionRefusedError(61, "Connection refused")
        exc = RedfishConnectionError(HOST, cause)
        self.assertEqual(exc.host, HOST)
        self.assertIs(exc.cause, cause)


class TestTimeoutErrorMessage(unittest.TestCase):
    def test_timeout_message_mentions_read_timeout(self) -> None:
        exc = RedfishTimeoutError(HOST)
        self.assertEqual(exc.host, HOST)
        msg = str(exc)
        self.assertIn("timed out", msg)
        self.assertIn("read_timeout", msg)
        # Should NOT falsely imply the port is closed.
        self.assertNotIn("Connection refused", msg)


if __name__ == "__main__":
    unittest.main()
