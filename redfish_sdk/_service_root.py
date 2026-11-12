"""Shared service-root configuration and URI reference resolution."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import SplitResult, unquote, urljoin, urlsplit

from .exceptions import RedfishValidationError

DEFAULT_SERVICE_ROOT = "/redfish/v1/"
SESSION_COLLECTION_PATH = "SessionService/Sessions"
_HTTP_SCHEMES = frozenset({"http", "https"})
_SCOPE_IDENTIFIER = re.compile(r"[A-Za-z0-9_.~-]+\Z")


def normalize_service_root(value: str) -> str:
    """Require an absolute URI path and normalize its trailing slash."""
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        raise RedfishValidationError("service_root must be an absolute path on the configured origin")
    decoded = unquote(value)
    if (any(c.isspace() for c in value) or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
            or "\\" in decoded or "?" in value or "#" in value or decoded.startswith("//")
            or any(part in {".", ".."} for part in decoded.split("/"))):
        raise RedfishValidationError("service_root must not contain queries, fragments or ambiguous path segments")
    return value.rstrip("/") + "/"


def resolve_service_url(origin: str, service_root: str, path: str) -> str:
    """Resolve bare paths under custom roots; preserve absolute paths and URLs.

    The default root retains legacy origin-relative bare request paths.
    Bare paths already containing a custom prefix also remain origin-relative. The transport must check the resolved origin before auth.
    """
    if (not isinstance(path, str) or "\\" in path or path.startswith("//")
            or any(ord(c) < 32 or ord(c) == 127 for c in path)):
        raise RedfishValidationError("Invalid Redfish request target")
    prefix = service_root.lstrip("/")
    try:
        reference_path = urlsplit(path).path
    except ValueError as exc:
        raise RedfishValidationError("Invalid Redfish request target") from exc
    if service_root == DEFAULT_SERVICE_ROOT or (
        prefix and (reference_path == prefix.rstrip("/") or reference_path.startswith(prefix))
    ):
        return urljoin(origin + "/", path)
    return urljoin(origin + service_root, path)


def validated_service_location(location: str) -> SplitResult:
    """Validate an untrusted discovery URL without resolving or contacting it."""
    if (not isinstance(location, str) or not location or "\\" in location
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in location)):
        raise RedfishValidationError("Invalid discovered service location")
    try:
        parts = urlsplit(location)
        port = parts.port
        host = parts.hostname
        if (parts.scheme not in _HTTP_SCHEMES or not host or not host.isascii()
                or parts.username is not None or parts.password is not None
                or "?" in location or "#" in location or port is not None and not 1 <= port <= 65535):
            raise ValueError("Invalid service origin")
        if ":" in host:
            address, separator, scope = host.partition("%25")
            ipaddress.IPv6Address(address)
            if separator and not _SCOPE_IDENTIFIER.fullmatch(scope):
                raise ValueError("Invalid IPv6 scope")
        elif "%" in host:
            raise ValueError("Encoded hostname is not supported")
        normalize_service_root(parts.path or "/")
        return parts
    except ValueError as exc:
        raise RedfishValidationError("Discovered locations require a valid HTTP(S) origin and service-root path") from exc
