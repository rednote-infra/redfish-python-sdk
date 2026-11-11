"""Redaction at diagnostic display boundaries, never on response attributes."""
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACTED = "<redacted>"
_SENSITIVE_LOG_KEYS = {
    "password", "username", "authenticationkey", "encryptionkey",
    "consoleurl", "credential", "secret", "token",
    "accesstoken", "authtoken", "xauthtoken", "httpheaders",
    "authorization", "proxyauthorization", "cookie", "setcookie",
}
_SENSITIVE_LOG_SUFFIXES = (
    "authorization", "community", "communitystring", "communitystrings",
    "consoleurl", "credential", "password", "secret", "token",
)


def redact_for_log(value: Any) -> Any:
    """Return a log-safe copy of request or response data."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            is_sensitive = normalized in _SENSITIVE_LOG_KEYS or normalized.endswith(_SENSITIVE_LOG_SUFFIXES)
            redacted[key] = _REDACTED if is_sensitive else redact_for_log(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_for_log(item) for item in value]
    if isinstance(value, str):
        try:
            parsed_json = json.loads(value)
        except (TypeError, ValueError):
            parsed_json = None
        if isinstance(parsed_json, (dict, list)):
            return json.dumps(redact_for_log(parsed_json))
        if "://" in value or (value.startswith("/") and "?" in value):
            parts = urlsplit(value)
            query = urlencode([(name, _REDACTED) for name, _ in parse_qsl(parts.query, keep_blank_values=True)])
            netloc = parts.netloc
            if parts.username is not None or parts.password is not None:
                host = parts.hostname or ""
                if parts.port is not None:
                    host = f"{host}:{parts.port}"
                netloc = f"{_REDACTED}@{host}"
            value = urlunsplit((parts.scheme, netloc, parts.path, query, ""))
        return re.sub(r"(?i)\b(Bearer|Basic)\s+[^\s,;\"']+", rf"\1 {_REDACTED}", value)
    return value


def redact_diagnostic(value: Any, secrets=()) -> str:
    """Also remove known credentials from free-text diagnostic output."""
    try:
        rendered = str(redact_for_log(value))
    except ValueError:
        # An invalid URL in a diagnostic must not mask the HTTP failure.
        rendered = _REDACTED
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        rendered = rendered.replace(secret, _REDACTED)
    return rendered
