"""
Redfish HTTP client — the core transport layer.

Provides low-level GET/POST/PATCH/DELETE operations against a Redfish BMC endpoint.

Design notes:
- Uses Basic Auth (base64-encoded "username:password") in Authorization header
- Skips SSL certificate verification (Redfish BMCs use self-signed certs)
- Supports HTTP proxy
- Extracts ETag from GET responses and sends If-Match on PATCH requests
- Raises RedfishException for non-2xx responses
- Connection timeout: 10s, Read timeout: 30s (configurable)

"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, Optional, Type, TypeVar

import requests
import urllib3
from pydantic import BaseModel

from .exceptions import (
    RedfishAuthError,
    RedfishConnectionError,
    RedfishException,
    RedfishNotFoundError,
    RedfishTimeoutError,
)

# Suppress InsecureRequestWarning for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# HTTP status codes that indicate success
_SUCCESS_CODES = {200, 201, 202, 204, 302}


def _filename_from_content_disposition(value: Optional[str]) -> Optional[str]:
    """
    Extract the filename from a ``Content-Disposition`` header, or None.

    Handles both ``filename="x.tar.gz"`` and the RFC 5987 ``filename*=`` form.
    """
    if not value:
        return None
    import re

    # RFC 5987: filename*=UTF-8''name  (take the part after the last quote/'')
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", value, re.IGNORECASE)
    if m:
        from urllib.parse import unquote

        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', value, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


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
    ):
        """
        Initialize the Redfish HTTP client.

        Args:
            host: BMC IP address or hostname (e.g., "192.0.2.10")
            username: BMC username
            password: BMC password
            verify_ssl: Whether to verify SSL certificates. Default False (BMCs use self-signed).
            proxy: Optional HTTP/HTTPS proxy URL (e.g., "http://127.0.0.1:8080")
            connect_timeout: Connection timeout in seconds
            read_timeout: Read timeout in seconds
            scheme: URL scheme, "https" (default) or "http"
            retry_5xx: Extra retries when the BMC returns a 5xx response
                (default 0 — no retry). GET/HEAD retry on any 5xx; POST /
                PATCH / DELETE retry only on 503/504 to avoid double-writes.
                Useful against overloaded or flaky BMCs that intermittently
                return ``InternalError`` (Base.1.x.InternalError) but recover
                on a second try.
            retry_on_read_timeout: When True, also retry on read timeouts
                (default False). Applies the same "GET always, writes only on
                503/504 equivalence" rule (writes retry as if the timeout is a
                503 — the request may still have hit the BMC, so use with care
                for non-idempotent operations).
            retry_backoff: Base sleep in seconds between retries; each retry
                sleeps ``retry_backoff * attempt`` (linear back-off).
        """
        self.host = host
        self.scheme = scheme
        self.verify_ssl = verify_ssl
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.retry_5xx = max(int(retry_5xx), 0)
        self.retry_on_read_timeout = bool(retry_on_read_timeout)
        self.retry_backoff = float(retry_backoff)

        # Pre-compute Basic Auth header (same as Java's base64 encoding)
        credentials = f"{username}:{password}"
        self._basic_auth = "Basic " + base64.b64encode(credentials.encode()).decode()

        # Session with proxy and default headers
        self._session = requests.Session()
        self._session.verify = verify_ssl
        self._session.headers.update({
            "Authorization": self._basic_auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}

        # Track the last ETag received for use in subsequent PATCH requests
        self._last_etag: Dict[str, str] = {}

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
    # Only these 5xx codes are retried for writes (POST/PATCH/DELETE) — 503
    # (Service Unavailable) and 504 (Gateway Timeout) usually mean the write
    # never reached the target, so retrying is generally safe. 500/502 on a
    # write is ambiguous (the change may have partially applied) — bubble up.
    _WRITE_RETRY_CODES = frozenset({503, 504})
    # All 5xx codes eligible for retry on reads.
    _READ_RETRY_CODES = frozenset({500, 502, 503, 504})

    def _should_retry_status(self, method: str, code: int) -> bool:
        """Return True when a retryable 5xx warrants another attempt."""
        if code < 500 or code > 599:
            return False
        if method.upper() in self._READ_METHODS:
            return code in self._READ_RETRY_CODES
        return code in self._WRITE_RETRY_CODES

    def _send(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Send an HTTP request with configurable retry on 5xx / read timeout.

        Reads (GET/HEAD) retry on any 5xx in the read-retry set; writes
        (POST/PATCH/DELETE) only retry on 503/504 to minimise double-write
        risk. When neither ``retry_5xx`` nor ``retry_on_read_timeout`` is set,
        this is a single-shot call — behaviour matches the original client.

        Raises the same transport exceptions as ``requests``; success or a
        terminal HTTP response (2xx or a non-retried 5xx / 4xx) is returned
        for the caller to interpret via :meth:`_raise_for_status`.
        """
        import time as _time

        method_u = method.upper()
        attempts = 1 + self.retry_5xx
        last_exc: Optional[BaseException] = None
        response: Optional[requests.Response] = None

        # Force a per-call timeout override to (connect, read) when the caller
        # did not pass one.
        kwargs.setdefault(
            "timeout", (self.connect_timeout, self.read_timeout)
        )
        url = self._build_url(path) if not path.startswith(("http://", "https://")) else path

        # Dispatch through the method-specific session attribute
        # (self._session.get / .post / ...). This keeps behaviour identical
        # to the pre-refactor client and preserves compatibility with unit
        # tests that stub the individual verbs.
        session_call = getattr(self._session, method_u.lower())
        for attempt in range(1, attempts + 1):
            try:
                response = session_call(url, **kwargs)
            except requests.exceptions.ReadTimeout as exc:
                last_exc = exc
                if (
                    self.retry_on_read_timeout
                    and (
                        method_u in self._READ_METHODS
                        # Writes: same idempotency caveat as 503/504 above.
                        or True
                    )
                    and attempt < attempts
                ):
                    logger.warning(
                        "%s %s read-timeout on attempt %d/%d; retrying",
                        method_u, url, attempt, attempts,
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
            if attempt < attempts and self._should_retry_status(method_u, code):
                logger.warning(
                    "%s %s -> HTTP %d on attempt %d/%d; retrying",
                    method_u, url, code, attempt, attempts,
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
            return self._send(method, path, **kwargs)
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

    def _raise_for_status(self, response: requests.Response, path: str) -> None:
        """
        Raise a typed RedfishException for non-2xx responses.
        """
        code = response.status_code
        if code in _SUCCESS_CODES:
            return

        body = ""
        try:
            body = response.text
        except Exception:
            pass

        logger.error("Request failed: %s %s -> HTTP %d, body: %s",
                     response.request.method, path, code, body[:500])

        if code in (401, 403):
            raise RedfishAuthError(code)
        if code == 404:
            raise RedfishNotFoundError(path)
        raise RedfishException(code, f"Request to {path} failed", body)

    def _parse(self, response: requests.Response, model_class: Type[T]) -> T:
        """Parse JSON response into a pydantic model."""
        try:
            data = response.json()
            return model_class.model_validate(data)
        except Exception as exc:
            logger.error("Failed to parse response as %s: %s", model_class.__name__, exc)
            raise RedfishException(
                response.status_code,
                f"Failed to parse response as {model_class.__name__}: {exc}",
                response.text[:1000],
            ) from exc

    # ------------------------------------------------------------------
    # Public HTTP methods
    # ------------------------------------------------------------------

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
        logger.debug("GET %s", path)
        response = self._request("GET", path)

        logger.debug("GET %s -> HTTP %d", path, response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)
        result = self._parse(response, model_class)

        # Store etag on the model itself if it's an Entity
        if hasattr(result, "odata_etag") and not result.odata_etag:
            etag = self._last_etag.get(path)
            if etag:
                result.odata_etag = etag

        return result

    def get_raw(self, path: str) -> Any:
        """
        Send a GET request and return the raw JSON dict (for dynamic structures).
        """
        logger.debug("GET (raw) %s", path)
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
            json_payload = body.model_dump(by_alias=True, exclude_none=True)
        elif raw_body is not None:
            json_payload = raw_body

        logger.info("POST %s, payload: %s", path, json_payload)
        response = self._request("POST", path, json=json_payload)

        logger.info("POST %s -> HTTP %d", path, response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)

        # 204 No Content — return empty model
        if response.status_code == 204 or not response.text.strip():
            return model_class.model_construct()

        return self._parse(response, model_class)

    def post_raw(self, path: str, body: Optional[Dict] = None) -> requests.Response:
        """
        Send a POST request and return the raw Response object.
        Useful when the caller needs response headers (e.g., X-Auth-Token).
        """
        logger.info("POST (raw) %s, payload: %s", path, body)
        response = self._request("POST", path, json=body)

        logger.info("POST (raw) %s -> HTTP %d", path, response.status_code)
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
        json_payload = body.model_dump(by_alias=True, exclude_none=True)

        headers = {"If-Match": etag}
        if extra_headers:
            headers.update(extra_headers)

        logger.info("PATCH %s, If-Match: %s, payload: %s", path, etag, json_payload)
        response = self._request("PATCH", path, json=json_payload, headers=headers)

        logger.info("PATCH %s -> HTTP %d", path, response.status_code)
        self._store_etag(path, response)
        self._raise_for_status(response, path)

        # 204 No Content
        if response.status_code == 204 or not response.text.strip():
            return model_class.model_construct()

        return self._parse(response, model_class)

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

        logger.info("PATCH (raw) %s, If-Match: %s, payload: %s", path, etag, body)
        response = self._request("PATCH", path, json=body, headers=headers)

        logger.info("PATCH (raw) %s -> HTTP %d", path, response.status_code)
        self._store_etag(path, response)
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
        logger.info("DELETE %s", path)
        response = self._request("DELETE", path)

        logger.info("DELETE %s -> HTTP %d", path, response.status_code)
        self._raise_for_status(response, path)
        return response.text

    def download(
        self,
        uri: str,
        output_path: Optional[str] = None,
        chunk_size: int = 65536,
    ) -> "bytes | str":
        """
        Download a binary artifact (e.g. a diagnostic-data bundle).

        Reuses the session's authentication (Basic/Token), ``verify_ssl`` and
        proxy configuration, so it works with BMCs whose artifact URIs require
        the same credentials as the Redfish API.

        A relative ``uri`` (starting with ``/``) is resolved against the BMC
        ``scheme://host``; an absolute ``http(s)://`` URI is used as-is.

        Args:
            uri: Absolute URL or Redfish-relative path of the artifact.
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
        import os

        logger.info("DOWNLOAD %s", uri)
        response = self._request("GET", uri, stream=True)

        logger.info("DOWNLOAD %s -> HTTP %d", uri, response.status_code)
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
    ) -> "bytes | str":
        """
        Trigger a binary download via POST (OEM ``DownloadAllLog`` schemes).

        Some BMCs (e.g. Inspur) return the log bundle directly in the body of
        a POST action rather than exposing a GET-able ``AdditionalDataURI``.

        Args:
            path: Redfish action path or absolute URL to POST to.
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
        import os

        logger.info("DOWNLOAD (POST) %s", path)
        response = self._request(
            "POST", path,
            json=raw_body if raw_body is not None else {},
            stream=True,
        )

        logger.info("DOWNLOAD (POST) %s -> HTTP %d", path, response.status_code)
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
            abs_path = os.path.join(abs_path, filename)

        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(abs_path, "wb") as fh:
            fh.write(content)

        logger.info("DOWNLOAD (POST) saved to %s", abs_path)
        return abs_path

    def set_auth_token(self, token: str) -> None:
        """
        Switch from Basic Auth to Session-based auth (X-Auth-Token).
        Called after successfully creating a session.
        """
        self._session.headers.pop("Authorization", None)
        self._session.headers["X-Auth-Token"] = token
        logger.debug("Switched to X-Auth-Token authentication")

    def reset_basic_auth(self) -> None:
        """Switch back to Basic Auth (e.g., after session deletion)."""
        self._session.headers.pop("X-Auth-Token", None)
        self._session.headers["Authorization"] = self._basic_auth
        logger.debug("Switched back to Basic Auth")

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self) -> RedfishHttpClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()
