"""Async transport/lifecycle regressions with a caller-owned mocked session."""
import asyncio
import json
import threading
import unittest
from unittest.mock import Mock, patch

import requests

import redfish_sdk as sdk

PATH = "/redfish/v1/Systems/Example"
SESSIONS = "/redfish/v1/SessionService/Sessions"
LOCATION = f"{SESSIONS}/Example"


class Response(requests.Response):
    def __init__(self, status=200, payload=None, headers=None):
        super().__init__()
        self.status_code = status
        self.headers.update(headers or {})
        self.encoding = "utf-8"
        self._content = json.dumps(payload or {}).encode()
        self._content_consumed = True


def session_response(payload=None):
    return Response(201, payload, {"X-Auth-Token": "new-token", "Location": LOCATION})


class AsyncClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = requests.Session()
        self.session.close = Mock(wraps=self.session.close)
        self.default_headers = dict(self.session.headers)
        self.client = sdk.AsyncRedfishClient("example.test", "test-user", "test-password",
            session=self.session, auth_mode=sdk.AuthenticationMode.BASIC)

    async def asyncTearDown(self):
        await self.client.close()
        self.session.close()

    async def test_all_verbs_and_options(self):
        for method in sdk.HttpMethod:
            self.session.request = Mock(return_value=Response(payload={"ok": True}))
            options = {} if method in (sdk.HttpMethod.GET, sdk.HttpMethod.HEAD) else {"body": {"Enabled": False}}
            result = await self.client.request(method, PATH, params={"$top": 1},
                headers={"X-Example": "test"}, read_timeout=90, **options)
            self.assertIsInstance(result, sdk.GenericResponse)
            self.assertTrue(result["ok"])
            kwargs = self.session.request.call_args.kwargs
            self.assertFalse(kwargs["allow_redirects"])
            self.assertTrue(kwargs["stream"])
            self.assertEqual(kwargs["params"], {"$top": 1})
            self.assertEqual(kwargs["timeout"][1], 90)
            self.assertIn("Authorization", kwargs["headers"])
            self.assertEqual(dict(self.session.headers), self.default_headers)

    async def test_https_only_and_same_origin(self):
        self.session.request = Mock()
        with self.assertRaises(sdk.RedfishValidationError):
            sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session, scheme="http")
        for target in ("https://other.example/path", "http://example.test/path", "//other.example/path"):
            with self.assertRaises(sdk.RedfishValidationError):
                await self.client.get(target)
        for header in ("Authorization", "x-auth-token"):
            with self.assertRaises(sdk.RedfishValidationError):
                await self.client.get(PATH, headers={header: "override"})
        self.session.request.assert_not_called()

    async def test_redirect_is_not_followed(self):
        self.session.request = Mock(return_value=Response(307, headers={"Location": "https://other.example/"}))
        result = await self.client.get(PATH)
        self.assertEqual(result.status_code, 307)
        self.session.request.assert_called_once()

    async def test_shared_error_semantics(self):
        payload = {"error": {"code": "Base.1.0.GeneralError", "message": " Original downstream message ",
            "@Message.ExtendedInfo": [{"MessageId": "Base.1.0.PropertyMissing", "RelatedProperties": ["#/Name"]}]}}
        self.session.request = Mock(return_value=Response(412, payload, {"Retry-After": "5"}))
        with self.assertRaises(sdk.RedfishPreconditionFailedError) as caught:
            await self.client.patch(PATH, body={})
        self.assertEqual(caught.exception.message, " Original downstream message ")
        self.assertEqual(caught.exception.code, "Base.1.0.GeneralError")
        self.assertEqual(caught.exception.related_properties, ["#/Name"])
        self.assertEqual(caught.exception.retry_after, "5")

    async def test_session_context_creates_and_deletes_only_redfish_session(self):
        self.session.request = Mock(side_effect=[Response(payload={"Links": {"Sessions": {"@odata.id": SESSIONS}}}),
            session_response(), Response(204)])
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session)
        async with client:
            self.assertEqual(client.session_key, "new-token")
        self.session.close.assert_not_called()
        calls = self.session.request.call_args_list
        self.assertEqual([call.args[0] for call in calls], ["GET", "POST", "DELETE"])
        self.assertNotIn("Authorization", calls[1].kwargs["headers"])
        self.assertEqual(calls[2].kwargs["headers"]["X-Auth-Token"], "new-token")

    async def test_existing_token_is_not_owned_or_deleted_on_close(self):
        self.session.request = Mock()
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session,
                                       session_key="external", session_location=LOCATION)
        await client.close()
        self.session.request.assert_not_called()
        self.session.close.assert_not_called()

    async def test_concurrent_expired_reads_refresh_once(self):
        def request(method, url, **kwargs):
            if method == "POST":
                return session_response()
            if method == "DELETE":
                return Response(204)
            if kwargs["headers"].get("X-Auth-Token") == "old-token":
                return Response(401)
            return Response(payload={"ok": True})
        self.session.request = Mock(side_effect=request)
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session,
                                       session_key="old-token", session_location=LOCATION)
        try:
            results = await asyncio.gather(*(client.get(PATH) for _ in range(4)))
            self.assertTrue(all(result["ok"] for result in results))
            self.assertEqual(sum(call.args[0] == "POST" for call in self.session.request.call_args_list), 1)
        finally:
            await client.close()

    async def test_writes_are_never_refreshed_or_replayed(self):
        self.session.request = Mock(return_value=Response(401))
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session,
                                       session_key="old-token", session_location=LOCATION)
        with self.assertRaises(sdk.RedfishAuthError):
            await client.delete(PATH, body={"Mode": "Example"})
        self.session.request.assert_called_once()
        await client.close()

    async def test_timeout_and_cancellation_types(self):
        self.session.request = Mock(side_effect=requests.Timeout())
        with self.assertRaises(sdk.RedfishTimeoutError):
            await self.client.get(PATH)
        self.session.request = Mock(side_effect=asyncio.CancelledError())
        with self.assertRaises(sdk.RedfishCancelledError) as caught:
            await self.client.get(PATH)
        self.assertIsInstance(caught.exception, asyncio.CancelledError)

    async def test_cancelled_request_context_cleans_up(self):
        root = Response(payload={"Links": {"Sessions": {"@odata.id": SESSIONS}}})
        self.session.request = Mock(side_effect=[root, session_response(), asyncio.CancelledError(), Response(204)])
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session)
        with self.assertRaises(asyncio.CancelledError):
            async with client:
                await client.get(PATH)
        self.assertEqual(self.session.request.call_args_list[-1].args[0], "DELETE")
        self.session.close.assert_not_called()

    async def test_restricted_context_entry_cleans_up(self):
        payload = {"@Message.ExtendedInfo": [{"MessageId": "Base.1.18.PasswordChangeRequired",
            "MessageArgs": ["/redfish/v1/AccountService/Accounts/Example"]}]}
        self.session.request = Mock(side_effect=[Response(payload={"Links": {"Sessions": {"@odata.id": SESSIONS}}}),
            session_response(payload), Response(204)])
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session)
        with self.assertRaises(sdk.RedfishPasswordChangeRequiredError):
            async with client:
                self.fail("Restricted login must fail context entry")
        self.assertEqual(self.session.request.call_args_list[-1].args[0], "DELETE")

    async def test_typed_model_getter(self):
        from redfish_sdk.models.systems import System
        self.session.request = Mock(return_value=Response(payload={"Id": "Example", "Name": "Server"}))
        result = await self.client.get_model(PATH, System)
        self.assertEqual(result.name, "Server")

    async def test_failed_refresh_is_shared_by_concurrent_readers(self):
        self.session.request = Mock(side_effect=lambda method, *args, **kwargs:
            Response(503, {"error": {"message": "Login unavailable"}}) if method == "POST" else Response(401))
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session,
            session_key="expired", session_location=LOCATION)
        results = await asyncio.gather(*(client.get(PATH) for _ in range(4)), return_exceptions=True)
        self.assertTrue(all(isinstance(result, sdk.RedfishServiceUnavailableError) for result in results))
        self.assertEqual(sum(call.args[0] == "POST" for call in self.session.request.call_args_list), 1)
        await client.close()

    async def test_cancelled_login_body_still_deletes_created_session(self):
        started, finish = threading.Event(), threading.Event()
        class SlowLogin(Response):
            @property
            def content(self):
                started.set()
                if not finish.wait(5):
                    raise AssertionError("Worker did not finish")
                return self._content
        self.session.request = Mock(side_effect=[Response(401),
            SlowLogin(201, headers={"X-Auth-Token": "new-token", "Location": LOCATION}), Response(204)])
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session)
        async def enter():
            async with client:
                self.fail("Cancelled login cannot enter the context")
        task = asyncio.create_task(enter())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
        finally:
            finish.set()
        with self.assertRaises(sdk.RedfishCancelledError):
            await task
        self.assertEqual(self.session.request.call_args_list[-1].args[0], "DELETE")
        self.session.close.assert_not_called()

    async def test_close_finishes_cleanup_when_caller_is_cancelled(self):
        started, finish = threading.Event(), threading.Event()
        class SlowDelete(Response):
            @property
            def content(self):
                started.set()
                if not finish.wait(5):
                    raise AssertionError("Worker did not finish")
                return self._content
        self.session.request = Mock(side_effect=[Response(401), session_response(), SlowDelete(204)])
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session)
        await client.login()
        task = asyncio.create_task(client.close())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
            self.assertFalse(task.done())
        finally:
            finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(task.cancelled())
        self.assertIsNone(client.session_key)
        self.session.close.assert_not_called()

    async def test_broken_error_body_preserves_status_and_allows_refresh(self):
        class Broken(Response):
            @property
            def content(self):
                raise requests.exceptions.ChunkedEncodingError("broken stream")
        self.session.request = Mock(return_value=Broken(412))
        with self.assertRaises(sdk.RedfishPreconditionFailedError):
            await self.client.patch(PATH, body={})
        self.session.request = Mock(side_effect=[Broken(401), session_response(), Response(), Response(204)])
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session,
            session_key="expired", session_location=LOCATION)
        await client.get(PATH)
        await client.close()

    async def test_explicit_null_and_nested_model_presence(self):
        from pydantic import BaseModel
        class Payload(BaseModel):
            clearable: object = None
            omitted: object = None
        self.session.request = Mock(return_value=Response())
        await self.client.patch(PATH, body=Payload(clearable=None))
        self.assertEqual(self.session.request.call_args.kwargs["json"], {"clearable": None})
        await self.client.patch(PATH, body=None)
        self.assertEqual(self.session.request.call_args.kwargs["data"], "null")

    async def test_reject_invalid_options_before_login(self):
        self.session.request = Mock()
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session)
        for options in ({"headers": []}, {"headers": {1: "test"}}, {"params": "invalid"},
                        {"read_timeout": 0}, {"allow_redirects": True}):
            with self.assertRaises(sdk.RedfishValidationError):
                await client.get(PATH, **options)
        self.session.request.assert_not_called()
        await client.close()

    async def test_bad_refresh_metadata_cannot_reuse_previous_session(self):
        self.session.request = Mock(side_effect=[Response(401), session_response(), Response(401),
            Response(201, headers={"X-Auth-Token": "incomplete-token"}), Response(204)])
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session)
        await client.login()
        with self.assertRaises(sdk.RedfishException):
            await client.get(PATH)
        await client.close()

    async def test_credentials_are_redacted_without_altering_error_attributes(self):
        secret = 'quote"and\\slash'
        client = sdk.AsyncRedfishClient("example.test", "test", secret, session=self.session,
            auth_mode=sdk.AuthenticationMode.BASIC)
        self.session.request = Mock(return_value=Response(400, {"error": {"message": f"Echo {secret}"}}))
        with self.assertRaises(sdk.RedfishBadRequestError) as caught:
            await client.post(PATH, body={})
        self.assertEqual(caught.exception.message, f"Echo {secret}")
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn(secret, repr(caught.exception))
        await client.close()

    async def test_requests_run_off_loop_and_serialize_the_caller_session(self):
        started, finish = threading.Event(), threading.Event()
        counter_lock = threading.Lock()
        active = maximum = 0
        worker_threads = set()
        loop_thread = threading.get_ident()
        def request(*args, **kwargs):
            nonlocal active, maximum
            with counter_lock:
                active += 1
                maximum = max(maximum, active)
                worker_threads.add(threading.get_ident())
            try:
                started.set()
                if not finish.wait(5):
                    raise AssertionError("Worker did not finish")
                return Response(payload={"ok": True})
            finally:
                with counter_lock:
                    active -= 1
        self.session.request = Mock(side_effect=request)
        tasks = [asyncio.create_task(self.client.get(PATH)) for _ in range(4)]
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            # The loop can continue while a synchronous network operation is blocked.
            await asyncio.sleep(0.01)
        finally:
            finish.set()
        results = await asyncio.gather(*tasks)
        self.assertTrue(all(result["ok"] for result in results))
        self.assertEqual(maximum, 1)
        self.assertNotIn(loop_thread, worker_threads)

    async def test_cancelled_write_waits_for_worker_and_never_replays(self):
        started, finish = threading.Event(), threading.Event()
        def request(*args, **kwargs):
            started.set()
            if not finish.wait(5):
                raise AssertionError("Worker did not finish")
            return Response(204)
        self.session.request = Mock(side_effect=request)
        task = asyncio.create_task(self.client.patch(PATH, body={"Enabled": False}))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
            self.assertFalse(task.done())
        finally:
            finish.set()
        with self.assertRaises(sdk.RedfishCancelledError):
            await task
        self.assertTrue(task.cancelled())
        self.session.request.assert_called_once()

    async def test_close_drains_inflight_requests_without_closing_caller_transport(self):
        started, finish = threading.Event(), threading.Event()
        def request(*args, **kwargs):
            started.set()
            if not finish.wait(5):
                raise AssertionError("Worker did not finish")
            return Response()
        self.session.request = Mock(side_effect=request)
        pending = asyncio.create_task(self.client.get(PATH))
        self.assertTrue(await asyncio.to_thread(started.wait, 5))
        closing = asyncio.create_task(self.client.close())
        try:
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
        finally:
            finish.set()
        await asyncio.gather(pending, closing)
        self.session.close.assert_not_called()

    async def test_netrc_cannot_override_managed_basic_authentication(self):
        adapter = Mock(spec=requests.adapters.BaseAdapter)
        adapter.send.return_value = Response()
        self.session.mount("https://", adapter)
        with patch("requests.sessions.get_netrc_auth", return_value=("unexpected", "credentials")) as netrc:
            await self.client.get(PATH)
        netrc.assert_not_called()
        prepared = adapter.send.call_args.args[0]
        self.assertEqual(prepared.headers["Authorization"], self.client._basic)
        self.assertTrue(adapter.send.call_args.kwargs["verify"])

    async def test_close_during_lazy_login_prevents_a_new_application_request(self):
        started, finish = threading.Event(), threading.Event()
        def request(method, url, **kwargs):
            if method == "POST":
                started.set()
                if not finish.wait(5):
                    raise AssertionError("Worker did not finish")
                return session_response()
            if method == "DELETE":
                return Response(204)
            return Response(401) if url.endswith("/redfish/v1/") else Response()
        self.session.request = Mock(side_effect=request)
        client = sdk.AsyncRedfishClient("example.test", "test", "test", session=self.session)
        pending = asyncio.create_task(client.get(PATH))
        self.assertTrue(await asyncio.to_thread(started.wait, 5))
        closing = asyncio.create_task(client.close())
        try:
            await asyncio.sleep(0)
        finally:
            finish.set()
        results = await asyncio.gather(pending, closing, return_exceptions=True)
        self.assertIsInstance(results[0], sdk.RedfishValidationError)
        self.assertIsNone(results[1])
        self.assertFalse(any(call.args[1].endswith(PATH) for call in self.session.request.call_args_list))
        self.assertEqual(self.session.request.call_args_list[-1].args[0], "DELETE")
