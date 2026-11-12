"""Configuration validation for caller-owned Requests transports."""
from __future__ import annotations

import os
from typing import Optional, Union

import requests

from .exceptions import RedfishValidationError

CaBundle = Union[str, os.PathLike[str]]
MANAGED_AUTH_HEADERS = frozenset({"authorization", "x-auth-token"})


class NoDefaultAuthentication(requests.auth.AuthBase):
    """Prevent netrc from replacing per-request authentication."""

    def __call__(self, request):
        return request


def validate_session(session: requests.Session) -> None:
    """Require credential-free defaults without modifying caller configuration."""
    if not isinstance(session, requests.Session):
        raise RedfishValidationError("Injected transport must be a requests.Session")
    if session.auth is not None or any(name.lower() in MANAGED_AUTH_HEADERS
                                       for name in session.headers):
        raise RedfishValidationError("Injected sessions must not define managed authentication")


def ca_bundle_path(value: Optional[CaBundle]) -> Optional[str]:
    """Normalize a public CA path; Requests validates certificate contents on use."""
    if value is None:
        return None
    try:
        path = os.fspath(value)
    except TypeError as exc:
        raise RedfishValidationError("ca_bundle must be a non-empty certificate bundle path") from exc
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        raise RedfishValidationError("ca_bundle must be a non-empty certificate bundle path")
    return path


def resolve_verify(verify_ssl, session: Optional[requests.Session], ca_path: Optional[str]):
    """Apply explicit CA/verification overrides before inherited session policy."""
    if ca_path is not None:
        return ca_path
    if verify_ssl or session is None:
        return verify_ssl
    return session.verify
