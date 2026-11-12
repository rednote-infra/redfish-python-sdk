"""
Redfish HTTP client — the core transport layer.

Provides low-level GET/POST/PATCH/DELETE operations against a Redfish BMC endpoint.

Design notes:
- Uses Basic Auth (base64-encoded "username:password") in Authorization header
- Preserves the legacy TLS default with a deprecation path toward verification
- Supports HTTP proxy
- Extracts ETag from GET responses and sends If-Match on PATCH requests
- Raises RedfishException for non-2xx responses
- Connection timeout: 10s, Read timeout: 30s (configurable)

"""
from __future__ import annotations

import base64
import logging
import math
import os
import re
import threading
import warnings
from http import HTTPStatus
from typing import Any, Dict, Mapping, Optional, Sequence, Type, TypeVar, Union
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests
from pydantic import BaseModel
from requests.structures import CaseInsensitiveDict

from ._errors import error_from_response
from ._redaction import redact_diagnostic
from ._redaction import redact_for_log as _redact_for_log
from ._tls import configure_tls_warnings
from ._transport import (
    MANAGED_AUTH_HEADERS,
    CaBundle,
    NoDefaultAuthentication,
    ca_bundle_path,
    resolve_verify,
    validate_session,
)
from .auth import AuthenticationMode
from .exceptions import (
    RedfishAuthError,
    RedfishConnectionError,
    RedfishException,
    RedfishMissingAttributeError,
    RedfishPasswordChangeRequiredError,
    RedfishTimeoutError,
    RedfishValidationError,
)
from .models.common import RedfishResponse
from .request import _JSON_NULL, _UNSET_BODY, HttpMethod, QueryParameters
from .response import GenericResponse
from .retry import RetryPolicy

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_EXPLICIT_REDIRECT_SUCCESS_CODES = frozenset({HTTPStatus.FOUND})
_REDIRECT_STATUSES = frozenset({
    HTTPStatus.MOVED_PERMANENTLY, HTTPStatus.FOUND, HTTPStatus.SEE_OTHER,
    HTTPStatus.TEMPORARY_REDIRECT, HTTPStatus.PERMANENT_REDIRECT,
})
_DEPRECATION_WARNINGS_EMITTED: set[str] = set()


def _warn_deprecated_once(key: str, message: str, stacklevel: int) -> None:
    """Emit a migration warning once per process without changing filters."""
    if key in _DEPRECATION_WARNINGS_EMITTED:
        return
    _DEPRECATION_WARNINGS_EMITTED.add(key)
    warnings.warn(message, DeprecationWarning, stacklevel=stacklevel)


def _serialize_mutation_body(body: BaseModel) -> Dict[str, Any]:
    """Serialize only explicitly supplied mutation fields, including nulls."""
    return body.model_dump(by_alias=True, exclude_unset=True)


def _filename_from_content_disposition(value: Optional[str]) -> Optional[str]:
    """
    Extract the filename from a ``Content-Disposition`` header, or None.

    Handles both ``filename="x.tar.gz"`` and the RFC 5987 ``filename*=`` form.
    """
    if not value:
        return None
    # RFC 5987: filename*=UTF-8''name  (take the part after the last quote/'')
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", value, re.IGNORECASE)
    if m:
        filename = unquote(m.group(1).strip().strip('"'))
        return _validate_download_filename(filename)
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', value, re.IGNORECASE)
    if m:
        return _validate_download_filename(unquote(m.group(1).strip()))
    return None


def _validate_download_filename(filename: str) -> str:
    """Validate a server-provided filename before using it on disk."""
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or os.path.isabs(filename)
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
    ):
        raise RedfishValidationError("Unsafe filename in Content-Disposition header")
    return filename


def _effective_port(parts) -> int:
    """Return the explicit or scheme-default port for parsed URL parts."""
    if parts.port is not None:
        return parts.port
    return 443 if parts.scheme.lower() == "https" else 80


def _same_origin(first_url: str, second_url: str) -> bool:
    """Return whether two HTTP(S) URLs use the same scheme, host, and port."""
    first = urlsplit(first_url)
    second = urlsplit(second_url)
    return (
        first.scheme.lower() == second.scheme.lower()
        and (first.hostname or "").lower() == (second.hostname or "").lower()
        and _effective_port(first) == _effective_port(second)
    )


class _CredentialSafeSession(requests.Session):
    """Requests session that removes Redfish credentials across origins."""

    def rebuild_auth(
        self,
        prepared_request: requests.PreparedRequest,
        response: requests.Response,
    ) -> None:
        if not _same_origin(response.request.url, prepared_request.url):
            prepared_request.headers.pop("Authorization", None)
            prepared_request.headers.pop("X-Auth-Token", None)
        super().rebuild_auth(prepared_request, response)


class RedfishHttpClient:
    """
    Low-level HTTP client for Redfish API calls.

    Usage:
        import os
        client = RedfishHttpClient(
            host=os.environ["BMC_IP"],
            username=os.environ["BMC_USERNAME"],
            password=os.environ["BMC_PASSWORD"],
            verify_ssl=False,
        )
        root = client.get("/redfish/v1/", RootService)
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        proxy: Optional[str] = None,
        connect_timeout: int = 10,
        read_timeout: int = 30,
        scheme: str = "https",
        retry_5xx: int = 0,
        retry_on_read_timeout: bool = False,
        retry_backoff: float = 1.0,
        allow_insecure_http_auth: Optional[bool] = None,
        auth_mode: AuthenticationMode | str = AuthenticationMode.BASIC,
        session_key: Optional[str] = None,
        session_location: Optional[str] = None,
        suppress_insecure_warnings: bool = True,
        session: Optional[requests.Session] = None,
        ca_bundle: Optional[CaBundle] = None,
        external_session: Optional[requests.Session] = None,
    ):
        """
        Initialize the Redfish HTTP client.

        Args:
            host: BMC IP address or hostname (e.g., "192.0.2.10")
            username: BMC username
            password: BMC password
            verify_ssl: Whether to verify SSL certificates. The legacy False
                default is preserved for compatibility but deprecated.
            proxy: Optional HTTP/HTTPS proxy URL (e.g., "http://127.0.0.1:8080")
            connect_timeout: Connection timeout in seconds
            read_timeout: Read timeout in seconds
            scheme: URL scheme, "https" (default) or "http"
            retry_5xx: Extra retries for GET/HEAD requests that receive a
                configured server-error response (default 0 — no retry).
                Writes retry only when an operation explicitly uses
                :attr:`RetryPolicy.IDEMPOTENT`.
            retry_on_read_timeout: When True, retry GET/HEAD read timeouts
                within the same retry bound. Writes retry only when an
                operation explicitly uses :attr:`RetryPolicy.IDEMPOTENT`.
            retry_backoff: Base sleep in seconds between retries; each retry
                sleeps ``retry_backoff * attempt`` (linear back-off).
            allow_insecure_http_auth: Control credentials over HTTP. Omitting
                this preserves the legacy allow behavior with a deprecation
                warning; False enforces HTTPS.
            auth_mode: Initial authentication mode. Use
                :class:`AuthenticationMode`; legacy string values remain
                accepted for compatibility.
            session_key: Existing Redfish session token. Supplying one enables
                session authentication immediately.
            session_location: Optional resource URI for an existing session,
                used for server-side cleanup and refresh.
            suppress_insecure_warnings: Hide this BMC hostname's unverified HTTPS
                warning when verify_ssl=False (default True). Set False to show
                it. Python warning policy is process-wide per hostname; other
                warnings and certificate verification errors are unaffected.
            session: Optional caller-owned Requests session for BMC traffic.
                Its defaults and adapters are not overwritten, and close() never
                closes it. Normal response hooks and cookie persistence remain
                active. Authentication is
                managed per request; session.auth and authentication defaults
                are rejected. Configure custom SSLContext/pooling/retries on its
                adapters. Caller adapters control their own retry behavior.
                Do not mutate or concurrently use the session outside the client.
            ca_bundle: CA bundle file or hashed CA directory path. Overrides
                verify_ssl and session.verify without changing a supplied session.
                Otherwise verify_ssl=True enables verification; the legacy False
                default preserves session.verify when a session is supplied.
                Set session.verify=False to explicitly disable injected TLS checks.
            external_session: Optional distinct caller-owned session for artifact
                downloads from other origins. Its own TLS policy is preserved
                unless ca_bundle or verify_ssl=True overrides it. Custom adapters,
                cookies and client certificates are not copied from the BMC
                session to other origins. SDK-created external sessions inherit
                BMC CA/proxy settings. Injected sessions never follow redirects
                automatically; request(..., allow_redirects=True) supports safe
                same-origin redirects explicitly.
        """
        if session is not None:
            validate_session(session)
        if external_session is not None:
            validate_session(external_session)
            if external_session is session:
                raise RedfishValidationError("external_session must be distinct from the BMC session")
        ca_path = ca_bundle_path(ca_bundle)
        effective_verify = resolve_verify(verify_ssl, session, ca_path)
        if not effective_verify:
            _warn_deprecated_once(
                "verify_ssl",
                "The legacy verify_ssl=False default is deprecated; pass "
                "verify_ssl=False explicitly for a self-signed BMC or "
                "verify_ssl=True to enable certificate verification.",
                stacklevel=3,
            )
        self._validate_endpoint(host, scheme, username, allow_insecure_http_auth)
        configure_tls_warnings(host, effective_verify, suppress_insecure_warnings)
        self.host = host
        self.scheme = scheme.lower()
        self.verify_ssl = effective_verify
        self._ca_bundle = ca_path
        self._proxy = proxy
        self._owns_session = session is None
        self._owns_external_session = external_session is None
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.retry_5xx = max(int(retry_5xx), 0)
        self.retry_on_read_timeout = bool(retry_on_read_timeout)
        self.retry_backoff = float(retry_backoff)
        try:
            auth_mode = AuthenticationMode(auth_mode)
        except (TypeError, ValueError) as exc:
            raise RedfishValidationError(
                "auth_mode must be a supported AuthenticationMode"
            ) from exc
        if session_key is not None:
            if not isinstance(session_key, str) or not session_key:
                raise RedfishValidationError(
                    "session_key must be a non-empty string"
                )
            auth_mode = AuthenticationMode.SESSION
        if session_location is not None and (
            not isinstance(session_location, str) or not session_location
        ):
            raise RedfishValidationError(
                "session_location must be a non-empty string"
            )
        if session_location is not None:
            self._resolve_url(session_location)

        # Pre-compute Basic Auth header (same as Java's base64 encoding)
        self._username = username
        self._password = password
        credentials = f"{username}:{password}"
        self._basic_auth = "Basic " + base64.b64encode(credentials.encode()).decode()
        self._auth_mode = auth_mode
        self._session_key: Optional[str] = None
        self._session_location: Optional[str] = None
        self._session_collection_uri = self._session_collection_from_location(
            session_location
        )
        self._session_refresh_lock = threading.Lock()
        self._session_refresh_failure: Optional[tuple[Optional[str], Exception]] = None

        # Session with proxy and default headers
        self._session = session if session is not None else _CredentialSafeSession()
        if self._owns_session:
            self._session.verify = effective_verify
            self._session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
            if auth_mode is AuthenticationMode.BASIC:
                self._session.headers[self._AUTHORIZATION_HEADER] = self._basic_auth
        if auth_mode is AuthenticationMode.SESSION and session_key is not None:
            self.set_auth_token(
                session_key,
                session_location=session_location,
            )

        self._external_session = external_session if external_session is not None else _CredentialSafeSession()
        self._external_verify = resolve_verify(verify_ssl, external_session, ca_path) if external_session is not None else effective_verify
        if self._owns_external_session:
            self._external_session.verify = self._external_verify
            self._external_session.headers.update({"Accept": "*/*"})
            if session is not None:
                self._external_session.proxies = dict(session.proxies)
                self._external_session.trust_env = session.trust_env

        if proxy:
            if self._owns_session:
                self._session.proxies = {"http": proxy, "https": proxy}
            if self._owns_external_session:
                self._external_session.proxies = {"http": proxy, "https": proxy}

        # Track the last ETag received for use in subsequent PATCH requests
        self._last_etag: Dict[str, str] = {}

    @staticmethod
    def _validate_endpoint(
        host: str,
        scheme: str,
        username: str,
        allow_insecure_http_auth: Optional[bool],
    ) -> None:
        """Validate the configured authenticated Redfish origin."""
        if (
            not isinstance(host, str)
            or not host
            or host != host.strip()
            or any(character.isspace() or ord(character) < 32 for character in host)
        ):
            raise RedfishValidationError("Redfish host must be a non-empty string")
        if not isinstance(scheme, str) or scheme.lower() not in {"http", "https"}:
            raise RedfishValidationError("Redfish scheme must be 'http' or 'https'")
        if not isinstance(username, str):
            raise RedfishValidationError("Redfish username must be a string")
        if ":" in username:
            _warn_deprecated_once(
                "colon_username",
                "A Basic authentication username containing ':' is ambiguous "
                "and will be rejected in the next major release.",
                stacklevel=5,
            )
        if scheme.lower() == "http":
            if allow_insecure_http_auth is False:
                raise RedfishValidationError(
                    "Authenticated Redfish connections require HTTPS when "
                    "allow_insecure_http_auth=False"
                )
            if allow_insecure_http_auth is None:
                _warn_deprecated_once(
                    "insecure_http",
                    "The legacy authenticated HTTP default is deprecated; pass "
                    "allow_insecure_http_auth=True to retain it explicitly or "
                    "False to require HTTPS.",
                    stacklevel=5,
                )

        try:
            endpoint = urlsplit(f"{scheme.lower()}://{host}")
            _ = endpoint.port
        except ValueError as exc:
            raise RedfishValidationError("Invalid Redfish host or port") from exc
        if (
            endpoint.scheme != scheme.lower()
            or endpoint.hostname is None
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
        ):
            raise RedfishValidationError(
                "Redfish host must contain only a hostname or IP address and optional port"
            )

    def _resolve_url(self, path: str) -> str:
        """Resolve a request target and require the configured BMC origin."""
        base = urlsplit(f"{self.scheme}://{self.host}")
        target = (
            urlsplit(path)
            if path.startswith(("http://", "https://"))
            else urlsplit(self._build_url(path))
        )
        try:
            same_origin = (
                target.scheme.lower() == base.scheme.lower()
                and (target.hostname or "").lower() == (base.hostname or "").lower()
                and _effective_port(target) == _effective_port(base)
                and target.username is None
                and target.password is None
            )
        except ValueError as exc:
            raise RedfishValidationError("Invalid Redfish request target") from exc
        if not same_origin:
            raise RedfishValidationError(
                "Refusing to send BMC credentials to a different origin"
            )
        return urlunsplit(target)

    def _is_same_origin_target(self, path: str) -> bool:
        """Return whether a request target belongs to the configured BMC."""
        if not path.startswith(("http://", "https://")):
            return True
        try:
            return _same_origin(f"{self.scheme}://{self.host}", path)
        except ValueError:
            return False

    @staticmethod
    def _validate_external_url(path: str) -> str:
        """Validate a credential-free cross-origin download URL."""
        try:
            target = urlsplit(path)
            _ = target.port
        except ValueError as exc:
            raise RedfishValidationError("Invalid artifact download URL") from exc
        if (
            target.scheme.lower() not in {"http", "https"}
            or target.hostname is None
            or target.username is not None
            or target.password is not None
        ):
            raise RedfishValidationError(
                "Cross-origin artifact URLs must be absolute HTTP(S) URLs "
                "without user information"
            )
        return urlunsplit(target)

    def _build_url(self, path: str) -> str:
        """Build a full URL from a Redfish path."""
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.scheme}://{self.host}{path}"

    def _get_etag(self, path: str, data: Optional[BaseModel]) -> str:
        """
        Get the ETag for a resource.
        If the model has an odata_etag attribute, use that; otherwise use '*' (wildcard).


        """
        if data is not None and hasattr(data, "odata_etag") and data.odata_etag:
            return data.odata_etag
        return self._last_etag.get(path, "*")

    def _store_etag(self, path: str, response: requests.Response) -> None:
        """
        Extract and store ETag from response headers.


        """
        etag = response.headers.get("ETag") or response.headers.get("etag")
        if etag:
            self._last_etag[path] = etag

    # HTTP methods that are safely retryable on any 5xx (idempotent reads).
    _READ_METHODS = frozenset({"GET", "HEAD"})
    _RETRY_STATUS_CODES = frozenset({
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    })
    _MANAGED_AUTH_HEADERS = MANAGED_AUTH_HEADERS
    _AUTHORIZATION_HEADER = "Authorization"
    _TOKEN_HEADER = "X-Auth-Token"
    _DEFAULT_SESSION_COLLECTION = "/redfish/v1/SessionService/Sessions"

    @property
    def auth_mode(self) -> AuthenticationMode:
        """Return the currently active authentication mode."""
        return self._auth_mode

    @property
    def session_location(self) -> Optional[str]:
        """Return the active server-side session resource URI."""
        return self._session_location

    @classmethod
    def _session_collection_from_location(
        cls, session_location: Optional[str]
    ) -> str:
        if not session_location:
            return cls._DEFAULT_SESSION_COLLECTION
        path = urlsplit(session_location).path.rstrip("/")
        parent = path.rsplit("/", 1)[0]
        return parent or cls._DEFAULT_SESSION_COLLECTION

    @classmethod
    def _validate_managed_headers(cls, headers: Any) -> None:
        if not headers:
            return
        if any(
            str(name).lower() in cls._MANAGED_AUTH_HEADERS
            for name in headers
        ):
            raise RedfishValidationError(
                "Per-request headers cannot replace managed authentication headers"
            )

    @classmethod
    def _can_retry(
        cls,
        method: str,
        retry_policy: RetryPolicy,
    ) -> bool:
        """Return whether the operation may be replayed safely."""
        return (
            method.upper() in cls._READ_METHODS
            or retry_policy is RetryPolicy.IDEMPOTENT
        )

    @classmethod
    def _should_retry_status(
        cls,
        method: str,
        code: int,
        retry_policy: RetryPolicy,
    ) -> bool:
        """Return True when policy permits retrying the response status."""
        return (
            cls._can_retry(method, retry_policy)
            and code in cls._RETRY_STATUS_CODES
        )

    def _send(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        bmc_login: bool = False,
        retry_policy: RetryPolicy = RetryPolicy.DEFAULT,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Send an HTTP request with configurable retry on 5xx / read timeout.

        Reads (GET/HEAD) use the configured bounded retry behavior. Writes are
        single-shot unless their operation explicitly declares
        :attr:`RetryPolicy.IDEMPOTENT`.

        Raises the same transport exceptions as ``requests``; success or a
        terminal HTTP response (2xx or a non-retried 5xx / 4xx) is returned
        for the caller to interpret via :meth:`_raise_for_status`.
        """
        import time as _time

        method_u = method.upper()
        if not isinstance(retry_policy, RetryPolicy):
            raise RedfishValidationError(
                "retry_policy must be a RetryPolicy member"
            )
        self._validate_managed_headers(kwargs.get("headers"))
        attempts = 1 + self.retry_5xx
        last_exc: Optional[BaseException] = None
        response: Optional[requests.Response] = None

        # Force a per-call timeout override to (connect, read) when the caller
        # did not pass one.
        kwargs.setdefault(
            "timeout", (self.connect_timeout, self.read_timeout)
        )
        url = (
            self._resolve_url(path)
            if authenticated or bmc_login
            else self._validate_external_url(path)
        )
        # Dispatch through the method-specific session attribute
        # (self._session.get / .post / ...). This keeps behaviour identical
        # to the pre-refactor client and preserves compatibility with unit
        # tests that stub the individual verbs.
        session = self._session if authenticated else self._external_session
        owned = self._owns_session if authenticated else self._owns_external_session
        verify = self.verify_ssl if authenticated else self._external_verify
        if bmc_login and not (self._owns_session and self._owns_external_session):
            session, owned, verify = self._session, self._owns_session, self.verify_ssl
        if not owned:
            validate_session(session)
            kwargs["allow_redirects"] = False
            kwargs["auth"] = NoDefaultAuthentication()
            request_headers = CaseInsensitiveDict(kwargs.get("headers") or {})
            for name, value in {"Accept": "application/json" if authenticated else "*/*",
                                "Content-Type": "application/json"}.items():
                if name not in session.headers:
                    request_headers.setdefault(name, value)
            if authenticated:
                if self._auth_mode is AuthenticationMode.BASIC:
                    request_headers[self._AUTHORIZATION_HEADER] = self._basic_auth
                elif self._session_key:
                    request_headers[self._TOKEN_HEADER] = self._session_key
            kwargs["headers"] = request_headers
            kwargs["verify"] = verify
        if bmc_login:
            kwargs["allow_redirects"] = False
            kwargs["auth"] = NoDefaultAuthentication()
            kwargs["headers"] = {**kwargs.get("headers", {}), self._AUTHORIZATION_HEADER: None,
                                 self._TOKEN_HEADER: None}
        if self._ca_bundle is not None:
            kwargs["verify"] = self._ca_bundle
        if self._proxy:
            kwargs["proxies"] = {"http": self._proxy, "https": self._proxy}
        session_call = getattr(session, method_u.lower())
        for attempt in range(1, attempts + 1):
            try:
                response = session_call(url, **kwargs)
            except requests.exceptions.ReadTimeout as exc:
                last_exc = exc
                if (
                    self.retry_on_read_timeout
                    and self._can_retry(method_u, retry_policy)
                    and attempt < attempts
                ):
                    logger.warning(
                        "%s %s read-timeout on attempt %d/%d; retrying",
                        method_u, _redact_for_log(url), attempt, attempts,
                    )
                    _time.sleep(self.retry_backoff * attempt)
                    continue
                raise
            except requests.exceptions.Timeout:
                # Connect timeouts are NOT retried here — they usually mean
                # the BMC is unreachable, not transiently overloaded.
                raise
            except requests.exceptions.ConnectionError:
                raise

            code = response.status_code
            if (
                attempt < attempts
                and self._should_retry_status(method_u, code, retry_policy)
            ):
                logger.warning(
                    "%s %s -> HTTP %d on attempt %d/%d; retrying",
                    method_u, _redact_for_log(url), code, attempt, attempts,
                )
                _time.sleep(self.retry_backoff * attempt)
                continue
            return response

        # attempts exhausted without a response (only reachable when we hit a
        # ReadTimeout on the last attempt without ``raise``); re-raise it.
        if response is None:
            assert last_exc is not None
            raise last_exc
        return response

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        retry_policy: RetryPolicy = RetryPolicy.DEFAULT,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Convenience wrapper: :meth:`_send` + transport-error translation.

        Reproduces the exact ``requests.Timeout``/``ConnectionError`` -> typed
        SDK exception mapping the public methods used to do inline, so
        replacing an inline ``self._session.get(...)`` block with a single
        ``self._request("GET", path)`` call is behaviour-preserving.
        """
        try:
            self._validate_managed_headers(kwargs.get("headers"))
            if (
                authenticated
                and self._auth_mode is AuthenticationMode.SESSION
                and self._session_key is None
            ):
                self._refresh_session(None)
            observed_session_key = self._session_key
            response = self._send(
                method,
                path,
                authenticated=authenticated,
                retry_policy=retry_policy,
                **kwargs,
            )
            if (
                authenticated
                and method.upper() in self._READ_METHODS
                and response.status_code == 401
                and self._auth_mode is AuthenticationMode.SESSION
            ):
                failure = self._response_error(response, path)
                if isinstance(failure, RedfishPasswordChangeRequiredError):
                    raise failure
                self._refresh_session(observed_session_key)
                response = self._send(
                    method,
                    path,
                    authenticated=authenticated,
                    retry_policy=retry_policy,
                    **kwargs,
                )
            return response
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

    def _raise_for_status(self, response: requests.Response, path: str) -> None:
        """
        Raise a typed RedfishException for non-2xx responses.
        """
        code = response.status_code
        if (
            HTTPStatus.OK <= code < HTTPStatus.MULTIPLE_CHOICES
            or code in _EXPLICIT_REDIRECT_SUCCESS_CODES
        ):
            return

        # 404 ("not found") is routinely an expected outcome handled by callers
        # via fallback (e.g. Chassis/1 -> Chassis/Self) or treated as "absent"
        # (e.g. optional sub-resources). Logging it at ERROR produces alarming
        # noise for what is normal control flow, so it is recorded at DEBUG only.
        # All other non-2xx responses remain at ERROR.
        failure = self._response_error(response, path)
        if code == HTTPStatus.NOT_FOUND:
            logger.debug("Request returned 404 (not found): %s %s",
                         failure.method, redact_diagnostic(path, self._diagnostic_secrets(response)))
        else:
            logger.error("Request failed: %s %s -> HTTP %d, body: %s",
                         failure.method, redact_diagnostic(path, self._diagnostic_secrets(response)), code,
                         redact_diagnostic(failure.body, self._diagnostic_secrets(response))[:500])
        raise failure

    def _diagnostic_secrets(self, response: Optional[requests.Response] = None):
        """Known credentials may be echoed in otherwise unstructured messages."""
        token = response.headers.get("X-Auth-Token") if response is not None else None
        return (self._password, self._session_key, self._basic_auth, token)

    def _response_error(self, response: requests.Response, path: str, *, secrets=()) -> Optional[RedfishException]:
        """Decode the standard error envelope without altering its raw data.

        Successful session responses can carry PasswordChangeRequired in their
        top-level extended info. Explicit logins supply attempted credentials
        before installing the restricted token; response tokens are also redacted.
        """
        try:
            body = response.text
        except requests.exceptions.RequestException:
            # Streaming/decoding failures must not replace the HTTP status or
            # block the normal 401 session-refresh path.
            body = ""
        return error_from_response(
            response.status_code, body, response.headers,
            method=getattr(response.request, "method", ""), path=path,
            secrets=self._diagnostic_secrets(response) + tuple(secrets),
        )

    def _parse(
        self,
        response: requests.Response,
        model_class: Type[T],
        resource_uri: str = "",
    ) -> T:
        """Parse JSON response into a pydantic model."""
        try:
            data = response.json()
            return model_class.model_validate(
                data,
                context={
                    "resource_uri": resource_uri,
                    "task_monitor_uri": response.headers.get("Location"),
                },
            )
        except RedfishMissingAttributeError:
            raise
        except Exception as exc:
            logger.error("Failed to parse response as %s", model_class.__name__)
            raise RedfishException(
                response.status_code,
                f"Failed to parse response as {model_class.__name__}",
                str(_redact_for_log(response.text))[:1000],
            ) from exc

    # ------------------------------------------------------------------
    # Public HTTP methods
    # ------------------------------------------------------------------

    def request(
        self, method: Union[HttpMethod, str], path: str, *,
        params: Optional[QueryParameters] = None,
        headers: Optional[Mapping[str, str]] = None, body: Any = _UNSET_BODY,
        connect_timeout: Optional[float] = None, read_timeout: Optional[float] = None,
        allow_redirects: bool = False, retry_policy: RetryPolicy = RetryPolicy.DEFAULT,
    ) -> GenericResponse:
        """Generic JSON request with explicit controls and preserved metadata.

        Redirects are returned by default. Explicit following is same-origin
        only, including scheme/port, and follows Requests' method-rewrite rules.
        No implicit ETag preflight/cache updates occur; pass conditional headers
        explicitly. Existing typed methods retain their own behavior.
        """
        try:
            verb = HttpMethod(method.upper())
        except (AttributeError, ValueError) as exc:
            raise RedfishValidationError("Unsupported generic HTTP method") from exc
        if not isinstance(retry_policy, RetryPolicy):
            raise RedfishValidationError("retry_policy must be a RetryPolicy member")
        if headers is not None and not isinstance(headers, Mapping):
            raise RedfishValidationError("headers must be a mapping")
        self._validate_managed_headers(headers)
        request_headers = CaseInsensitiveDict(headers or {})
        if params is not None:
            valid_params = (isinstance(params, Mapping) and all(isinstance(key, str) for key in params)) or (
                isinstance(params, Sequence) and not isinstance(params, (str, bytes)) and all(
                    isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[0], str) for pair in params
                )
            )
            if not valid_params:
                raise RedfishValidationError("params must be a mapping or a sequence of key/value pairs")
        if not isinstance(allow_redirects, bool):
            raise RedfishValidationError("allow_redirects must be a boolean")
        timeout = (
            self.connect_timeout if connect_timeout is None else connect_timeout,
            self.read_timeout if read_timeout is None else read_timeout,
        )
        for value in timeout:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise RedfishValidationError("Request timeouts must be finite positive numbers")
        if verb in (HttpMethod.GET, HttpMethod.HEAD) and body is not _UNSET_BODY:
            raise RedfishValidationError("GET and HEAD do not accept a generic request body")
        if isinstance(body, BaseModel):
            body = _serialize_mutation_body(body)
        options = {"params": params, "headers": request_headers, "timeout": timeout, "allow_redirects": False}
        if body is None:
            options["data"] = _JSON_NULL
        elif body is not _UNSET_BODY:
            options["json"] = body
        target = self._resolve_url(path)
        redirects = 0
        while True:
            response = self._request(verb.value, target, retry_policy=retry_policy, **options)
            location = response.headers.get("Location")
            if not allow_redirects or response.status_code not in _REDIRECT_STATUSES or not location:
                break
            if redirects >= self._session.max_redirects:
                raise RedfishValidationError("Generic request exceeded the redirect limit")
            # Resolve/validate before sending the next request: stripping auth
            # alone would still expose a POST/PUT body on a cross-origin 307.
            target = self._resolve_url(urljoin(response.url or target, location))
            options.pop("params", None)
            if ((response.status_code in (HTTPStatus.FOUND, HTTPStatus.SEE_OTHER) and verb != HttpMethod.HEAD)
                    or (response.status_code == HTTPStatus.MOVED_PERMANENTLY and verb == HttpMethod.POST)):
                verb = HttpMethod.GET
                options.pop("json", None)
                options.pop("data", None)
                for name in ("Content-Length", "Content-Type", "Transfer-Encoding"):
                    request_headers[name] = None
            redirects += 1
        if not HTTPStatus.MULTIPLE_CHOICES <= response.status_code < HTTPStatus.BAD_REQUEST:
            self._raise_for_status(response, target)
        return GenericResponse.from_response(response)

    def get(self, path: str, model_class: Type[T]) -> T:
        """
        Send a GET request and return the parsed response.

        Args:
            path: Redfish resource path (e.g., "/redfish/v1/Systems/1")
            model_class: Pydantic model class to deserialize the response into

        Returns:
            Parsed model instance

        Raises:
            RedfishException: On non-2xx HTTP responses
            RedfishConnectionError: On network errors
            RedfishTimeoutError: On timeout
        """
        logger.debug("GET %s", _redact_for_log(path))
        response = self._request("GET", path)

        logger.debug("GET %s -> HTTP %d", _redact_for_log(path), response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)
        result = self._parse(response, model_class, path)

        # Store etag on the model itself if it's an Entity
        if hasattr(result, "odata_etag"):
            etag = response.headers.get("ETag")
            if etag:
                result.odata_etag = etag

        return result

    def get_raw(self, path: str) -> Any:
        """
        Send a GET request and return the raw JSON dict.

        .. important::
           **Reserved for low-level exploration and diagnostic tooling.**
           Production code inside ``redfish_sdk/`` MUST NOT call this: use
           :meth:`get` with a typed pydantic model instead. Reaching for
           ``get_raw`` in feature code means the resource has no model yet —
           add one to ``redfish_sdk/models/`` first. This is enforced by
           convention (see PR discussion on log-collection refactor); the
           only sanctioned callers are:

             * ``tools/*.py`` — diagnostic scripts for unknown BMCs
             * third-party callers exploring OEM structures interactively

        Returns the parsed JSON as a plain ``dict``/``list`` structure.
        """
        logger.debug("GET (raw) %s", _redact_for_log(path))
        response = self._request("GET", path)

        self._store_etag(path, response)
        self._raise_for_status(response, path)
        return response.json()

    def post(self, path: str, model_class: Type[T], body: Optional[BaseModel] = None,
             raw_body: Optional[Dict] = None) -> T:
        """
        Send a POST request and return the parsed response.

        Args:
            path: Redfish resource path
            model_class: Pydantic model to deserialize response into
            body: Optional pydantic model to serialize as request body
            raw_body: Optional raw dict as request body (alternative to body)

        Returns:
            Parsed model instance

        Raises:
            RedfishException: On non-2xx HTTP responses
        """
        json_payload = None
        if body is not None:
            json_payload = _serialize_mutation_body(body)
        elif raw_body is not None:
            json_payload = raw_body

        logger.info("POST %s, payload: %s", _redact_for_log(path), _redact_for_log(json_payload))
        response = self._request("POST", path, json=json_payload)

        logger.info("POST %s -> HTTP %d", _redact_for_log(path), response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)

        # 204 No Content — return empty model
        if response.status_code == 204 or not response.text.strip():
            result = model_class.model_construct()
        else:
            result = self._parse(response, model_class, path)

        if isinstance(result, RedfishResponse):
            result.task_monitor = response.headers.get("Location") or result.task_monitor
            result.http_status = response.status_code
            result.task_uri = result.odata_id or result.task_uri
            result.retry_after = response.headers.get("Retry-After") or result.retry_after
        else:
            # Preserve response metadata needed by the standard diagnostic-log
            # flow. Import lazily to keep the transport module independent of
            # higher-level service managers.
            from .models.task import Task

            if isinstance(result, Task):
                location = response.headers.get("Location")
                result.initial_http_status = response.status_code
                result.initial_location = location
                result.initial_content_location = response.headers.get(
                    "Content-Location"
                )
                result.initial_retry_after = response.headers.get("Retry-After")
                result.task_monitor = result.task_monitor or location
                if (
                    not result.odata_id
                    and location
                    and "/TaskService/Tasks/" in location
                    and "/TaskMonitors/" not in location
                ):
                    result.odata_id = location
        return result

    def post_raw(self, path: str, body: Optional[Dict] = None) -> requests.Response:
        """
        Send a POST request and return the raw Response object.
        Useful when the caller needs response headers (e.g., X-Auth-Token).
        """
        logger.info("POST (raw) %s, payload: %s", _redact_for_log(path), _redact_for_log(body))
        response = self._request("POST", path, json=body)

        logger.info("POST (raw) %s -> HTTP %d", _redact_for_log(path), response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)
        return response

    def post_multipart(
        self, path: str, files: Dict[str, Any], fields: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """POST multipart data with a replayable body and no payload logging.

        Requests generates the boundary. Encoding once keeps a complete body
        available if the configured transport retries the upload. Field values
        can use Requests' file tuple format to set per-part content types.
        """
        parts = []
        for name, value in (fields or {}).items():
            part = value if isinstance(value, tuple) else (None, value)
            parts.append((name, part))
        parts.extend(files.items())
        prepared = requests.Request(
            "POST", self._build_url("/"), files=parts
        ).prepare()
        response = self._request(
            "POST", path, data=prepared.body,
            headers={"Content-Type": prepared.headers["Content-Type"]},
        )
        logger.info("POST multipart %s -> HTTP %d", _redact_for_log(path), response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)
        return response

    def patch(self, path: str, model_class: Type[T], body: BaseModel,
              extra_headers: Optional[Dict[str, str]] = None) -> T:
        """
        Send a PATCH request and return the parsed response.

        Automatically sets the If-Match header using the ETag from the entity
        (or '*' if no ETag is available).

        Args:
            path: Redfish resource path
            model_class: Pydantic model to deserialize response into
            body: Pydantic model to serialize as request body (must be Entity for ETag)
            extra_headers: Additional headers to include (e.g., Content-Type overrides)

        Returns:
            Parsed model instance

        Raises:
            RedfishException: On non-2xx HTTP responses
        """
        etag = self._get_etag(path, body)
        json_payload = _serialize_mutation_body(body)

        headers = {"If-Match": etag}
        if extra_headers:
            headers.update(extra_headers)

        logger.info(
            "PATCH %s, If-Match: %s, payload: %s",
            _redact_for_log(path), etag, _redact_for_log(json_payload),
        )
        response = self._request("PATCH", path, json=json_payload, headers=headers)

        logger.info("PATCH %s -> HTTP %d", _redact_for_log(path), response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)

        # 204 No Content
        if response.status_code == 204 or not response.text.strip():
            return model_class.model_construct()

        return self._parse(response, model_class, path)

    def patch_raw(self, path: str, body: Dict, extra_headers: Optional[Dict[str, str]] = None) -> requests.Response:
        """
        Send a PATCH request with a raw dict body and return the raw Response object.

        Automatically sets the If-Match header using the cached ETag
        (or '*' if no ETag is available).

        Args:
            path: Redfish resource path
            body: Raw dict to serialize as JSON request body
            extra_headers: Additional headers to include

        Returns:
            Raw Response object

        Raises:
            RedfishException: On non-2xx HTTP responses
        """
        etag = self._last_etag.get(path, "*")

        headers = {"If-Match": etag}
        if extra_headers:
            headers.update(extra_headers)

        logger.info(
            "PATCH (raw) %s, If-Match: %s, payload: %s",
            _redact_for_log(path), etag, _redact_for_log(body),
        )
        response = self._request("PATCH", path, json=body, headers=headers)

        logger.info("PATCH (raw) %s -> HTTP %d", _redact_for_log(path), response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)
        return response

    def delete_raw(self, path: str) -> requests.Response:
        """Send DELETE and preserve the complete successful HTTP response."""
        logger.info("DELETE %s", _redact_for_log(path))
        response = self._request("DELETE", path)

        logger.info("DELETE %s -> HTTP %d", _redact_for_log(path), response.status_code)
        self._raise_for_status(response, path)
        return response

    def delete(self, path: str) -> str:
        """
        Send a DELETE request.

        Args:
            path: Redfish resource path

        Returns:
            Response body as string (usually empty for 204)

        Raises:
            RedfishException: On non-2xx HTTP responses
        """
        return self.delete_raw(path).text

    def download(
        self,
        uri: str,
        output_path: Optional[str] = None,
        chunk_size: int = 65536,
    ) -> bytes | str:
        """
        Download a binary artifact (e.g. a diagnostic-data bundle).

        Same-origin downloads reuse the session's authentication (Basic/Token),
        ``verify_ssl`` and proxy configuration. Cross-origin absolute URLs use
        a credential-free session with the same transport configuration.

        A relative ``uri`` is resolved against the BMC ``scheme://host``.
        Redirects remain enabled for backward compatibility, while the session
        strips Redfish credentials before following a redirect to another
        origin.

        Args:
            uri: Absolute HTTP(S) URL or Redfish-relative artifact path.
            output_path: When provided, stream the body to this path (creating
                parent directories) and return the absolute file path. When
                ``None``, return the full content as ``bytes``.
            chunk_size: Streaming chunk size in bytes (default 64 KiB).

        Returns:
            The file bytes when ``output_path`` is ``None``; otherwise the
            absolute path of the written file.

        Raises:
            RedfishException: On non-2xx HTTP responses.
            RedfishConnectionError / RedfishTimeoutError: On transport errors.
        """
        logger.info("DOWNLOAD %s", _redact_for_log(uri))
        response = self._request(
            "GET",
            uri,
            authenticated=self._is_same_origin_target(uri),
            stream=True,
        )

        logger.info("DOWNLOAD %s -> HTTP %d", _redact_for_log(uri), response.status_code)
        self._raise_for_status(response, uri)

        if output_path is None:
            return response.content

        abs_path = os.path.abspath(output_path)
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(abs_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    fh.write(chunk)

        logger.info("DOWNLOAD saved to %s", abs_path)
        return abs_path

    def download_via_post(
        self,
        path: str,
        output_path: Optional[str] = None,
        raw_body: Optional[Dict] = None,
    ) -> bytes | str:
        """
        Trigger a binary download via POST (OEM ``DownloadAllLog`` schemes).

        Some BMCs (e.g. Inspur) return the log bundle directly in the body of
        a POST action rather than exposing a GET-able ``AdditionalDataURI``.

        Args:
            path: Redfish action path or same-origin absolute URL to POST to.
            output_path: When ``None``, return the body as ``bytes``. When a
                directory, the filename from ``Content-Disposition`` is used
                (falling back to the last path segment). When a file path,
                the body is written there. Returns the absolute file path.
            raw_body: Optional POST body dict (defaults to ``{}``).

        Returns:
            The bundle bytes, or the absolute written file path.

        Raises:
            RedfishException: On non-2xx HTTP responses.
        """
        logger.info("DOWNLOAD (POST) %s", _redact_for_log(path))
        response = self._request(
            "POST", path,
            json=raw_body if raw_body is not None else {},
            stream=True,
        )

        logger.info("DOWNLOAD (POST) %s -> HTTP %d", _redact_for_log(path), response.status_code)
        self._raise_for_status(response, path)

        content = response.content
        if output_path is None:
            return content

        abs_path = os.path.abspath(output_path)
        # When output_path is an existing directory (or ends with a separator),
        # derive the filename from Content-Disposition.
        if os.path.isdir(abs_path) or output_path.endswith(os.sep):
            filename = _filename_from_content_disposition(
                response.headers.get("Content-Disposition")
            ) or path.rstrip("/").rsplit("/", 1)[-1] or "download.bin"
            output_dir = os.path.realpath(abs_path)
            abs_path = os.path.realpath(os.path.join(output_dir, filename))
            if os.path.commonpath((output_dir, abs_path)) != output_dir:
                raise RedfishValidationError(
                    "Download filename escapes the requested output directory"
                )

        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(abs_path, "wb") as fh:
            fh.write(content)

        logger.info("DOWNLOAD (POST) saved to %s", abs_path)
        return abs_path

    def set_auth_token(
        self,
        token: str,
        *,
        session_location: Optional[str] = None,
        session_collection_uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        """
        Switch from Basic Auth to Session-based auth (X-Auth-Token).
        Called after successfully creating a session.
        """
        if not isinstance(token, str) or not token:
            raise RedfishValidationError(
                "Redfish session token must be a non-empty string"
            )
        if username is not None:
            self._username = username
        if password is not None:
            self._password = password
        if session_collection_uri:
            self._session_collection_uri = session_collection_uri
        elif session_location:
            self._session_collection_uri = self._session_collection_from_location(
                session_location
            )
        self._auth_mode = AuthenticationMode.SESSION
        self._session_key = token
        self._session_location = session_location
        self._session_refresh_failure = None
        if self._owns_session:
            self._session.headers.pop(self._AUTHORIZATION_HEADER, None)
            self._session.headers[self._TOKEN_HEADER] = token
        logger.debug("Switched to X-Auth-Token authentication")

    def reset_basic_auth(self) -> None:
        """Switch back to Basic Auth (e.g., after session deletion)."""
        self._auth_mode = AuthenticationMode.BASIC
        self._session_key = None
        self._session_location = None
        self._session_refresh_failure = None
        if self._owns_session:
            self._session.headers.pop(self._TOKEN_HEADER, None)
            self._session.headers[self._AUTHORIZATION_HEADER] = self._basic_auth
        logger.debug("Switched back to Basic Auth")

    def _refresh_session(self, observed_session_key: Optional[str]) -> None:
        """Refresh an expired session once, synchronized across callers."""
        with self._session_refresh_lock:
            if (
                observed_session_key is not None
                and self._session_key != observed_session_key
            ):
                return
            try:
                if (
                    self._session_refresh_failure is not None
                    and self._session_refresh_failure[0] == observed_session_key
                ):
                    raise self._session_refresh_failure[1]
                try:
                    response = self._send(
                        "POST", self._session_collection_uri,
                        authenticated=False, bmc_login=True,
                        json={
                            "UserName": self._username,
                            "Password": self._password,
                        },
                        timeout=(self.connect_timeout, self.read_timeout),
                    )
                except requests.exceptions.Timeout as exc:
                    raise RedfishTimeoutError(self.host) from exc
                except requests.exceptions.ConnectionError as exc:
                    raise RedfishConnectionError(self.host, exc) from exc
                self._raise_for_status(response, self._session_collection_uri)
                token = response.headers.get("X-Auth-Token")
                if not token:
                    raise RedfishAuthError(401)
                self.set_auth_token(
                    token,
                    session_location=response.headers.get("Location"),
                    session_collection_uri=self._session_collection_uri,
                )
                restriction = self._response_error(response, self._session_collection_uri)
                if restriction:
                    raise restriction
            except Exception as exc:
                self._session_refresh_failure = (observed_session_key, exc)
                raise

    def clear_active_session(self, session_location: str) -> None:
        """Restore Basic auth after the active server session is deleted."""
        if not self._session_location:
            return
        try:
            active = self._resolve_url(self._session_location).rstrip("/")
            deleted = self._resolve_url(session_location).rstrip("/")
        except RedfishValidationError:
            return
        if active == deleted:
            self.reset_basic_auth()

    def logout(self, *, suppress_errors: bool = False) -> None:
        """Delete the active server-side session and clear local token state."""
        session_location = self._session_location
        try:
            if session_location:
                response = self._send("DELETE", session_location)
                self._raise_for_status(response, session_location)
        except Exception as exc:
            if not suppress_errors:
                raise
            logger.warning(
                "Unable to delete active Redfish session during cleanup: %s",
                exc,
            )
        finally:
            self.reset_basic_auth()

    def close(self) -> None:
        """Best-effort logout, then close only SDK-owned HTTP sessions."""
        try:
            if self._auth_mode is AuthenticationMode.SESSION:
                self.logout(suppress_errors=True)
        finally:
            if self._owns_session:
                self._session.close()
            if self._owns_external_session:
                self._external_session.close()

    def __enter__(self) -> RedfishHttpClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()
