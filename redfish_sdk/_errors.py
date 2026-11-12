"""Shared decoding for buffered Redfish error responses."""
from http import HTTPStatus

from .exceptions import (
    RedfishAuthError,
    RedfishBadRequestError,
    RedfishConflictError,
    RedfishException,
    RedfishNotFoundError,
    RedfishPasswordChangeRequiredError,
    RedfishPreconditionFailedError,
    RedfishRateLimitError,
    RedfishServiceUnavailableError,
)
from .models.common import RedfishErrorResponse

_EXPLICIT_REDIRECT_SUCCESS_CODES = frozenset({HTTPStatus.FOUND})
_HTTP_ERROR_TYPES = {
    HTTPStatus.BAD_REQUEST: RedfishBadRequestError,
    HTTPStatus.CONFLICT: RedfishConflictError,
    HTTPStatus.PRECONDITION_FAILED: RedfishPreconditionFailedError,
    HTTPStatus.TOO_MANY_REQUESTS: RedfishRateLimitError,
    HTTPStatus.SERVICE_UNAVAILABLE: RedfishServiceUnavailableError,
}
_PASSWORD_CHANGE_MESSAGE = "PasswordChangeRequired"
_BASE_REGISTRY = "Base"


def error_from_response(status_code, body, headers, *, method="", path="", secrets=()):
    """Preserve the downstream message and structured details without rewriting raw data."""
    try:
        envelope = RedfishErrorResponse.model_validate_json(body)
    except ValueError:
        envelope = None
    error = envelope.error if envelope else None
    messages = list(error.extended_info or []) if error else []
    if envelope:
        messages.extend(envelope.extended_info or [])
    message = error.message if error else None
    if not message or not message.strip():
        message = next((info.message for info in messages if info.message and info.message.strip()), "")

    details = {
        "error": error, "extended_info": messages,
        "retry_after": headers.get("Retry-After"),
        "request_id": headers.get("X-Request-ID"),
        "method": method, "path": path,
        "secrets": secrets,
    }
    identifiers = [(error.code, None)] if error else []
    identifiers.extend((info.message_id, info.message_args) for info in messages)
    password_required = False
    account_uri = None
    for identifier, arguments in identifiers:
        parts = (identifier or "").split(".")
        if (len(parts) == 4 and parts[0] == _BASE_REGISTRY
                and parts[1].isdigit() and parts[2].isdigit()
                and parts[3] == _PASSWORD_CHANGE_MESSAGE):
            password_required = True
            if arguments and arguments[0].strip():
                account_uri = arguments[0]
    code = status_code
    if password_required:
        return RedfishPasswordChangeRequiredError(code, message, body, account_uri=account_uri, **details)
    if HTTPStatus.OK <= code < HTTPStatus.MULTIPLE_CHOICES or code in _EXPLICIT_REDIRECT_SUCCESS_CODES:
        return None
    if code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        return RedfishAuthError(code, message, body, **details)
    if code == HTTPStatus.NOT_FOUND:
        details.pop("path")
        return RedfishNotFoundError(path, message, body, **details)
    exception_type = _HTTP_ERROR_TYPES.get(code, RedfishException)
    return exception_type(code, message or f"Request to {path} failed", body, **details)
