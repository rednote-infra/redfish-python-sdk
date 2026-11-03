"""Metadata-preserving response type for generic Redfish operations."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

import requests
from requests.structures import CaseInsensitiveDict

_HEADER_CONTENT_LOCATION = "Content-Location"
_HEADER_LOCATION = "Location"
_HEADER_RETRY_AFTER = "Retry-After"


@dataclass(eq=False, repr=False)
class GenericResponse(Mapping[str, Any]):
    """HTTP response returned by generic POST, PATCH, and DELETE methods.

    The object preserves transport metadata and raw content. It also behaves
    as a read-only mapping when the response contains a JSON object, providing
    a compatibility path for callers that previously consumed a dictionary.
    """

    status_code: int
    headers: CaseInsensitiveDict[str]
    content: bytes
    text: str
    json_data: Any = None
    json_error: Optional[str] = None
    has_json: bool = False
    _empty_body: bool = field(default=False, repr=False)

    @classmethod
    def from_response(cls, response: requests.Response) -> GenericResponse:
        """Create a generic response without requiring successful JSON parsing."""
        text = getattr(response, "text", "")
        content = getattr(response, "content", None)
        if content is None or (not content and text):
            encoding = getattr(response, "encoding", None) or "utf-8"
            content = text.encode(encoding, errors="replace")
        else:
            content = bytes(content)

        empty_body = not content or not text.strip()
        json_data: Any = None
        json_error: Optional[str] = None
        has_json = False
        if not empty_body:
            try:
                json_data = json.loads(text)
                has_json = True
            except (json.JSONDecodeError, TypeError) as exc:
                json_error = str(exc)

        return cls(
            status_code=response.status_code,
            headers=CaseInsensitiveDict(getattr(response, "headers", {})),
            content=content,
            text=text,
            json_data=json_data,
            json_error=json_error,
            has_json=has_json,
            _empty_body=empty_body,
        )

    @property
    def status(self) -> int:
        """Compatibility alias for the HTTP status code."""
        return self.status_code

    @property
    def http_status(self) -> int:
        """Return the HTTP status code using the SDK operation naming."""
        return self.status_code

    @property
    def location(self) -> Optional[str]:
        """Return the response Location header, if present."""
        return self.headers.get(_HEADER_LOCATION)

    @property
    def task_monitor(self) -> Optional[str]:
        """Return the asynchronous task-monitor URI, if advertised."""
        return self.location

    @property
    def retry_after(self) -> Optional[str]:
        """Return the Retry-After header without discarding vendor formats."""
        return self.headers.get(_HEADER_RETRY_AFTER)

    @property
    def content_location(self) -> Optional[str]:
        """Return the Content-Location header, if present."""
        return self.headers.get(_HEADER_CONTENT_LOCATION)

    def json(self) -> Any:
        """Return parsed JSON, or the legacy empty mapping for an empty body.

        Parsing errors are raised only when JSON is explicitly requested; the
        response object remains available for inspection through ``content``,
        ``text``, ``headers``, and ``json_error``.
        """
        if self._empty_body:
            return {}
        if self.has_json:
            return self.json_data
        raise ValueError(
            "Response body is not valid JSON; inspect content, text, and "
            "json_error for the original response"
        )

    def as_dict(self) -> dict[str, Any]:
        """Return legacy dictionary semantics for empty or JSON-object bodies."""
        data = self.json()
        if not isinstance(data, dict):
            raise TypeError("Response JSON is not an object")
        return data

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            try:
                return self.as_dict() == dict(other)
            except (TypeError, ValueError):
                return False
        return NotImplemented

    def __repr__(self) -> str:
        return (
            f"GenericResponse(status_code={self.status_code}, "
            f"content_length={len(self.content)}, has_json={self.has_json})"
        )
