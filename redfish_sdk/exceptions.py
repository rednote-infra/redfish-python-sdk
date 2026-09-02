"""
Custom exceptions for the Redfish Python SDK.
"""


class RedfishException(Exception):
    """
    Base exception for all Redfish SDK errors.

    Raised when a Redfish API call returns a non-successful HTTP status code.
    """

    def __init__(self, status_code: int, message: str, body: str = ""):
        self.status_code = status_code
        self.message = message
        self.body = body
        super().__init__(f"[HTTP {status_code}] {message}")

    def __repr__(self) -> str:
        return f"RedfishException(status_code={self.status_code}, message={self.message!r})"


class RedfishNotFoundError(RedfishException):
    """Raised when a resource is not found (HTTP 404)."""

    def __init__(self, path: str):
        super().__init__(404, f"Resource not found: {path}")


class RedfishAuthError(RedfishException):
    """Raised when authentication fails (HTTP 401 / 403)."""

    def __init__(self, status_code: int = 401):
        super().__init__(status_code, "Authentication failed. Check username and password.")


class RedfishConnectionError(RedfishException):
    """Raised when unable to connect to the BMC."""

    def __init__(self, host: str, cause: Exception = None):
        super().__init__(0, f"Unable to connect to host: {host}. Cause: {cause}")
        self.cause = cause


class RedfishTimeoutError(RedfishException):
    """Raised when a request times out."""

    def __init__(self, host: str):
        super().__init__(0, f"Request timed out connecting to: {host}")


class RedfishValidationError(RedfishException):
    """Raised for invalid input parameters (e.g., unsupported reset type)."""

    def __init__(self, message: str):
        super().__init__(400, message)


class LogCollectFailedError(RedfishException):
    """
    Raised when out-of-band diagnostic-data collection fails on the BMC.

    Carries the full BMC context so the caller can diagnose without having to
    re-query the BMC: the terminal task state/status, the complete list of
    BMC messages, and (when available) the history of progress snapshots
    observed while polling.

    Attributes:
        task_id: Task or synthetic-task identifier the collection ran under.
        task_state: Terminal ``TaskState`` reported by the BMC.
        task_status: Terminal ``TaskStatus`` reported by the BMC.
        messages: Full ``Messages`` list from the BMC (each entry retains its
            ``MessageId`` / ``Message`` / ``Severity`` / ``Resolution`` fields).
        progress_history: Optional list of intermediate progress snapshots
            captured during polling — useful for vendors (e.g. ZTE) whose
            progress endpoint replaces earlier state on each poll.
    """

    def __init__(
        self,
        message: str,
        *,
        task_id: str = "",
        task_state: str = "",
        task_status: str = "",
        messages: list = None,
        progress_history: list = None,
    ):
        super().__init__(500, message)
        self.task_id = task_id
        self.task_state = task_state
        self.task_status = task_status
        self.messages = messages or []
        self.progress_history = progress_history or []
