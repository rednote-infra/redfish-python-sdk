"""Unverified HTTPS warning policy preserves other diagnostics and TLS errors."""
import unittest
import warnings
from unittest.mock import Mock

import requests

from redfish_sdk import (
    AsyncRedfishClient,
    AuthenticationMode,
    RedfishClient,
    RedfishConnectionError,
    RedfishValidationError,
)
from redfish_sdk.http_client import RedfishHttpClient

HOST = "example.test"
PATH = "/redfish/v1/"
WARNING_MODULE = "urllib3.connectionpool"


def emit_warning(host=HOST, *, message=None, module=WARNING_MODULE):
    warnings.warn_explicit(message or f"Unverified HTTPS request is being made to host '{host}'. Details",
        Warning, "connectionpool.py", 100, module=module)


def response_with_warnings(*args, **kwargs):
    emit_warning()
    emit_warning("other.example")
    emit_warning(message="Unrelated diagnostic")
    emit_warning(module="another.module")
    response = requests.Response()
    response.status_code = 200
    response._content = b"{}"
    return response


class TlsWarningTests(unittest.TestCase):
    def test_default_client_hides_only_this_hosts_unverified_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client = RedfishClient(HOST, "test", "test")
            client._http_client._session.get = Mock(side_effect=response_with_warnings)
            client.request("GET", PATH)
            client.close()
        visible = [str(item.message) for item in caught if item.category is Warning]
        self.assertEqual(len(visible), 3)
        self.assertTrue(any("other.example" in message for message in visible))
        self.assertIn("Unrelated diagnostic", visible)

    def test_opt_out_restores_warning_for_the_same_host(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            quiet = RedfishHttpClient(HOST, "test", "test")
            noisy = RedfishHttpClient(HOST, "test", "test", suppress_insecure_warnings=False)
            noisy._session.get = Mock(side_effect=response_with_warnings)
            noisy.get_raw(PATH)
            quiet.close()
            noisy.close()
        self.assertTrue(any(item.category is Warning and f"'{HOST}'" in str(item.message) for item in caught))

    def test_verified_client_leaves_warning_filters_unchanged_and_preserves_tls_errors(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            before = list(warnings.filters)
            client = RedfishHttpClient(HOST, "test", "test", verify_ssl=True)
            self.assertEqual(warnings.filters, before)
            client._session.get = Mock(side_effect=requests.exceptions.SSLError("Untrusted certificate"))
            with self.assertRaises(RedfishConnectionError):
                client.get_raw(PATH)
            client.close()

    def test_option_requires_boolean(self):
        for constructor in (RedfishHttpClient, RedfishClient):
            with self.assertRaises(RedfishValidationError):
                constructor(HOST, "test", "test", suppress_insecure_warnings="yes")

    def test_actual_urllib3_warning_is_hidden_for_a_host_with_a_port(self):
        from urllib3.connectionpool import HTTPSConnectionPool
        from urllib3.exceptions import InsecureRequestWarning
        connection = Mock(host=HOST, is_closed=False, is_verified=False, proxy_is_verified=False)
        pool = HTTPSConnectionPool(HOST, port=8443)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client = RedfishHttpClient(f"{HOST}:8443", "test", "test")
            pool._validate_conn(connection)
            self.assertFalse(any(item.category is InsecureRequestWarning for item in caught))
            client.close()
            noisy = RedfishHttpClient(f"{HOST}:8443", "test", "test", suppress_insecure_warnings=False)
            pool._validate_conn(connection)
            self.assertTrue(any(item.category is InsecureRequestWarning for item in caught))
            noisy.close()
        connection.connect.assert_not_called()


class AsyncTlsWarningTests(unittest.IsolatedAsyncioTestCase):
    async def test_unverified_requests_session_uses_the_same_warning_policy(self):
        with warnings.catch_warnings(record=True) as caught, requests.Session() as session:
            warnings.simplefilter("always")
            session.verify = False
            session.request = Mock(side_effect=response_with_warnings)
            async with AsyncRedfishClient(HOST, "test", "test", session=session,
                    auth_mode=AuthenticationMode.BASIC) as client:
                await client.get(PATH)
        self.assertEqual(len([item for item in caught if item.category is Warning]), 3)
