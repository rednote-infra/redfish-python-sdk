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
        """
        self.host = host
        self.scheme = scheme
        self.verify_ssl = verify_ssl
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

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
        url = self._build_url(path)
        logger.debug("GET %s", url)

        try:
            response = self._session.get(
                url, timeout=(self.connect_timeout, self.read_timeout)
            )
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

        logger.debug("GET %s -> HTTP %d", url, response.status_code)
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
        url = self._build_url(path)
        logger.debug("GET (raw) %s", url)
        try:
            response = self._session.get(
                url, timeout=(self.connect_timeout, self.read_timeout)
            )
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

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
        url = self._build_url(path)
        json_payload = None
        if body is not None:
            json_payload = body.model_dump(by_alias=True, exclude_none=True)
        elif raw_body is not None:
            json_payload = raw_body

        logger.info("POST %s, payload: %s", url, json_payload)

        try:
            response = self._session.post(
                url,
                json=json_payload,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

        logger.info("POST %s -> HTTP %d", url, response.status_code)
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
        url = self._build_url(path)
        logger.info("POST (raw) %s, payload: %s", url, body)
        try:
            response = self._session.post(
                url,
                json=body,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

        logger.info("POST (raw) %s -> HTTP %d", url, response.status_code)
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
        url = self._build_url(path)
        etag = self._get_etag(path, body)
        json_payload = body.model_dump(by_alias=True, exclude_none=True)

        headers = {"If-Match": etag}
        if extra_headers:
            headers.update(extra_headers)

        logger.info("PATCH %s, If-Match: %s, payload: %s", url, etag, json_payload)

        try:
            response = self._session.patch(
                url,
                json=json_payload,
                headers=headers,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

        logger.info("PATCH %s -> HTTP %d", url, response.status_code)
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
        url = self._build_url(path)
        etag = self._last_etag.get(path, "*")

        headers = {"If-Match": etag}
        if extra_headers:
            headers.update(extra_headers)

        logger.info("PATCH (raw) %s, If-Match: %s, payload: %s", url, etag, body)

        try:
            response = self._session.patch(
                url,
                json=body,
                headers=headers,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

        logger.info("PATCH (raw) %s -> HTTP %d", url, response.status_code)
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
        url = self._build_url(path)
        logger.info("DELETE %s", url)

        try:
            response = self._session.delete(
                url, timeout=(self.connect_timeout, self.read_timeout)
            )
        except requests.exceptions.Timeout as exc:
            raise RedfishTimeoutError(self.host) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RedfishConnectionError(self.host, exc) from exc

        logger.info("DELETE %s -> HTTP %d", url, response.status_code)
        self._raise_for_status(response, path)
        return response.text

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
