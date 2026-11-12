"""Optional asyncio transport using a caller-owned aiohttp session."""
from __future__ import annotations

import asyncio
import base64
import logging
import math
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Optional, Type, TypeVar
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel
from requests.structures import CaseInsensitiveDict

from ._errors import error_from_response
from .auth import AuthenticationMode
from .exceptions import (
    RedfishCancelledError,
    RedfishConnectionError,
    RedfishException,
    RedfishPasswordChangeRequiredError,
    RedfishTimeoutError,
    RedfishValidationError,
)
from .models.common import Link
from .models.root import RootService
from .models.session import SessionService
from .request import _JSON_NULL, _UNSET_BODY, HttpMethod, QueryParameters
from .response import GenericResponse

if TYPE_CHECKING:
    import aiohttp

T = TypeVar("T", bound=BaseModel)
_ROOT = "/redfish/v1/"
_SESSIONS = "/redfish/v1/SessionService/Sessions"
_AUTHORIZATION = "Authorization"
_TOKEN = "X-Auth-Token"
_LOCATION = "Location"
_MANAGED_HEADERS = frozenset({_AUTHORIZATION.lower(), _TOKEN.lower()})
_SAFE_METHODS = frozenset({HttpMethod.GET, HttpMethod.HEAD})
logger = logging.getLogger(__name__)


class AsyncRedfishClient:
    """Additive async JSON client; install ``redfish-python-sdk[async]``.

    Supply an open ``aiohttp.ClientSession`` created in the running event loop.
    The caller controls TLS verification, proxies, pooling, tracing and transport
    shutdown. The SDK never closes that session or changes its default headers.
    Use a session without default authentication or credential headers.

    HTTPS and same-origin targets are required; redirects are returned, never
    followed. GET/HEAD refresh an expired Redfish session once, coordinated among
    concurrent readers. Writes are never replayed. Timeouts become
    RedfishTimeoutError; transport failures become RedfishConnectionError.
    RedfishCancelledError inherits asyncio.CancelledError, preserving cancellation.
    Async contexts clean up SDK-created Redfish sessions, including on failed
    entry and cancellation. Supplied tokens are not deleted by close().
    """

    def __init__(self, host: str, username: str, password: str, *, session: aiohttp.ClientSession,
                 scheme: str = "https", auth_mode=AuthenticationMode.SESSION,
                 session_key: Optional[str] = None, session_location: Optional[str] = None,
                 connect_timeout: float = 10, read_timeout: float = 30):
        try:
            import aiohttp
        except ImportError as exc:
            raise ImportError("Install redfish-python-sdk[async] to use AsyncRedfishClient") from exc
        if scheme.lower() != "https":
            raise RedfishValidationError("Async authentication requires HTTPS")
        self._origin = f"https://{host}"
        parts = urlsplit(self._origin)
        if not parts.hostname or parts.username is not None or parts.path or parts.query or parts.fragment:
            raise RedfishValidationError("host must contain only a hostname or IP address and optional port")
        try:
            self._port = parts.port or 443
            self.auth_mode = AuthenticationMode(auth_mode)
        except ValueError as exc:
            raise RedfishValidationError("Invalid endpoint port or authentication mode") from exc
        if ":" in username:
            raise RedfishValidationError("Basic authentication usernames cannot contain a colon")
        if not isinstance(session, aiohttp.ClientSession) or session.closed:
            raise RedfishValidationError("session must be an open aiohttp.ClientSession")
        self._validate_headers(session.headers)
        if session.auth is not None:
            raise RedfishValidationError("Caller session must not supply default authentication")
        self.host = host
        self._username, self._password = username, password
        self._basic = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        self._session, self._aiohttp = session, aiohttp
        self.connect_timeout = self._timeout(connect_timeout)
        self.read_timeout = self._timeout(read_timeout)
        self.session_key = session_key
        self.session_location = self._url(session_location) if session_location else None
        self._sessions_uri = self.session_location.rsplit("/", 1)[0] if self.session_location else None
        self._owned = False
        self._closed = False
        self._lock = asyncio.Lock()
        self._generation = 0
        self._refresh_failure = None
        self._close_task = None

    @staticmethod
    def _timeout(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise RedfishValidationError("Timeouts must be positive finite numbers")
        return value

    @staticmethod
    def _validate_headers(headers):
        if not isinstance(headers, Mapping) or any(
                not isinstance(key, str) or key.lower() in _MANAGED_HEADERS for key in headers):
            raise RedfishValidationError("Authentication headers are managed by the async client")

    def _url(self, path):
        if not isinstance(path, str) or not path or path.startswith("//") or "\\" in path or any(ord(c) < 32 for c in path):
            raise RedfishValidationError("Invalid Redfish request target")
        url = urljoin(self._origin + "/", path)
        parts = urlsplit(url)
        try:
            valid = (parts.scheme == "https" and parts.hostname == urlsplit(self._origin).hostname
                     and (parts.port or 443) == self._port and parts.username is None and not parts.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise RedfishValidationError("Redfish requests must remain on the configured HTTPS origin")
        return url

    def _check_open(self):
        if self._closed or self._close_task is not None:
            raise RedfishValidationError("Async client is closed")

    def _error(self, response, method, path, *, secrets=()):
        return error_from_response(response.status_code, response.text, response.headers,
            method=method.value, path=path,
            secrets=(self._password, self.session_key, self._basic, response.headers.get(_TOKEN), *secrets))

    def _install_session(self, token, location):
        if token and location:
            location = self._url(location)
            self.session_key, self.session_location = token, location
            self._owned = True
            self._generation += 1

    async def _wire(self, method, path, *, authenticated=True, capture_session=False, headers=None,
                    params=None, body=_UNSET_BODY, connect_timeout=None, read_timeout=None):
        request_headers = CaseInsensitiveDict(headers or {})
        if authenticated:
            if self.auth_mode == AuthenticationMode.SESSION and self.session_key:
                request_headers[_TOKEN] = self.session_key
            else:
                request_headers[_AUTHORIZATION] = self._basic
        options = {}
        if body is not _UNSET_BODY:
            if isinstance(body, BaseModel):
                body = body.model_dump(by_alias=True, exclude_unset=True)
            if body is None:
                options["data"] = _JSON_NULL
                request_headers.setdefault("Content-Type", "application/json")
            else:
                options["json"] = body
        timeout = self._aiohttp.ClientTimeout(total=None,
            connect=self._timeout(self.connect_timeout if connect_timeout is None else connect_timeout),
            sock_read=self._timeout(self.read_timeout if read_timeout is None else read_timeout))
        try:
            async with self._session.request(method.value, self._url(path), headers=request_headers,
                    params=params, timeout=timeout, allow_redirects=False, raise_for_status=False, **options) as raw:
                headers = CaseInsensitiveDict(raw.headers)
                # Capture ownership before awaiting the body, so cancelled login can be cleaned up.
                if capture_session and HTTPStatus.OK <= raw.status < HTTPStatus.MULTIPLE_CHOICES:
                    self._install_session(headers.get(_TOKEN), headers.get(_LOCATION))
                try:
                    content = await raw.read()
                except self._aiohttp.ClientPayloadError:
                    if raw.status < HTTPStatus.BAD_REQUEST:
                        raise
                    content = b""
                return GenericResponse.from_content(raw.status, headers, content, encoding=raw.charset or "utf-8")
        except asyncio.CancelledError:
            raise RedfishCancelledError("Async Redfish operation cancelled") from None
        except asyncio.TimeoutError as exc:
            raise RedfishTimeoutError(self.host) from exc
        except self._aiohttp.ClientError as exc:
            # Keep transport exception text out of display surfaces; it may echo credentials.
            raise RedfishConnectionError(self.host, type(exc).__name__) from None

    async def request(self, method, path: str, *, params: Optional[QueryParameters] = None,
                      headers=None, body: Any = _UNSET_BODY, connect_timeout=None,
                      read_timeout=None, allow_redirects: bool = False) -> GenericResponse:
        """Perform one buffered JSON operation; preserve response metadata and errors."""
        self._check_open()
        self._url(path)
        try:
            method = HttpMethod(method.upper())
        except (ValueError, AttributeError) as exc:
            raise RedfishValidationError("Unsupported HTTP method") from exc
        self._validate_headers({} if headers is None else headers)
        if params is not None:
            valid_params = (isinstance(params, Mapping) and all(isinstance(key, str) for key in params)) or (
                isinstance(params, Sequence) and not isinstance(params, (str, bytes)) and all(
                    isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[0], str) for pair in params
                )
            )
            if not valid_params:
                raise RedfishValidationError("params must be a mapping or a sequence of key/value pairs")
        if allow_redirects:
            raise RedfishValidationError("Async redirects must be handled explicitly by the caller")
        if method in _SAFE_METHODS and body is not _UNSET_BODY:
            raise RedfishValidationError("GET and HEAD do not accept a JSON body")
        for value in (connect_timeout, read_timeout):
            if value is not None:
                self._timeout(value)
        if self.auth_mode == AuthenticationMode.SESSION and not self.session_key:
            await self._refresh(self._generation)
        generation = self._generation
        secrets = (self.session_key,)
        response = await self._wire(method, path, params=params, headers=headers, body=body,
            connect_timeout=connect_timeout, read_timeout=read_timeout)
        failure = self._error(response, method, path, secrets=secrets)
        if (response.status_code == HTTPStatus.UNAUTHORIZED and method in _SAFE_METHODS
                and self.auth_mode == AuthenticationMode.SESSION
                and not isinstance(failure, RedfishPasswordChangeRequiredError)):
            await self._refresh(generation)
            secrets = (self.session_key,)
            response = await self._wire(method, path, params=params, headers=headers,
                connect_timeout=connect_timeout, read_timeout=read_timeout)
            failure = self._error(response, method, path, secrets=secrets)
        if response.status_code >= HTTPStatus.BAD_REQUEST or isinstance(failure, RedfishPasswordChangeRequiredError):
            raise failure
        return response

    async def _discover_sessions(self):
        response = await self._wire(HttpMethod.GET, _ROOT, authenticated=False)
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            return _SESSIONS
        failure = self._error(response, HttpMethod.GET, _ROOT)
        if failure:
            raise failure
        root = RootService.model_validate_json(response.text)
        if root.links and root.links.sessions and root.links.sessions.odata_id:
            return root.links.sessions.odata_id
        if root.session_service and root.session_service.odata_id:
            uri = root.session_service.odata_id
            response = await self._wire(HttpMethod.GET, uri, authenticated=False)
            failure = self._error(response, HttpMethod.GET, uri)
            if failure:
                raise failure
            service = SessionService.model_validate_json(response.text)
            if service.sessions and service.sessions.odata_id:
                return service.sessions.odata_id
        return _SESSIONS

    async def _login(self):
        if not self._sessions_uri:
            self._sessions_uri = await self._discover_sessions()
        response = await self._wire(HttpMethod.POST, self._sessions_uri, authenticated=False,
            capture_session=True, body={"UserName": self._username, "Password": self._password})
        location = response.location
        if HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES and not location:
            location = Link.model_validate_json(response.text).odata_id
            self._install_session(response.headers.get(_TOKEN), location)
        failure = self._error(response, HttpMethod.POST, self._sessions_uri)
        if failure:
            raise failure
        if not (HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES
                and response.headers.get(_TOKEN) and location):
            raise RedfishException(response.status_code, "Session response must include a token and safe session URI")

    async def _refresh(self, generation):
        async with self._lock:
            self._check_open()
            if self._refresh_failure and self._refresh_failure[0] == generation:
                raise self._refresh_failure[1]
            if self._generation != generation:
                return
            try:
                await self._login()
            except Exception as exc:
                self._refresh_failure = (generation, exc)
                raise

    async def login(self):
        """Authenticate explicitly; restricted successful sessions remain available for recovery."""
        self._check_open()
        if self.auth_mode == AuthenticationMode.BASIC:
            return
        async with self._lock:
            self._check_open()
            if not self.session_key or self._refresh_failure:
                self._refresh_failure = None
                await self._login()

    async def logout(self):
        """Explicitly delete the current Redfish session, including a supplied one."""
        async with self._lock:
            try:
                if self.session_key and self.session_location:
                    response = await self._wire(HttpMethod.DELETE, self.session_location)
                    failure = self._error(response, HttpMethod.DELETE, self.session_location)
                    if failure:
                        raise failure
            finally:
                self.session_key = self.session_location = None
                self._owned = False
                self._generation += 1

    async def _cleanup(self):
        try:
            # Wait for an in-flight login before deciding whether a session is owned.
            async with self._lock:
                owned = self._owned
            if owned:
                await self.logout()
        except Exception as exc:
            logger.warning("Redfish session cleanup failed (%s)", type(exc).__name__)
        finally:
            self._closed = True

    async def close(self):
        """Clean up SDK-owned remote sessions without closing the caller's transport."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._cleanup())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await asyncio.shield(self._close_task)
            raise RedfishCancelledError("Async Redfish cleanup cancelled") from None

    async def __aenter__(self):
        try:
            await self.login()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def get_model(self, path: str, model_class: Type[T], **kwargs) -> T:
        """Deserialize a successful GET directly into the requested response model."""
        response = await self.get(path, **kwargs)
        return model_class.model_validate_json(response.text, context={"resource_uri": path})

    async def get(self, path, **kwargs) -> GenericResponse:
        return await self.request(HttpMethod.GET, path, **kwargs)

    async def head(self, path, **kwargs) -> GenericResponse:
        return await self.request(HttpMethod.HEAD, path, **kwargs)

    async def post(self, path, **kwargs) -> GenericResponse:
        return await self.request(HttpMethod.POST, path, **kwargs)

    async def put(self, path, **kwargs) -> GenericResponse:
        return await self.request(HttpMethod.PUT, path, **kwargs)

    async def patch(self, path, **kwargs) -> GenericResponse:
        return await self.request(HttpMethod.PATCH, path, **kwargs)

    async def delete(self, path, **kwargs) -> GenericResponse:
        return await self.request(HttpMethod.DELETE, path, **kwargs)
