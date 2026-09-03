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
    """
    Raised when unable to connect to the BMC.

    The message includes a category-specific troubleshooting hint derived
    from the underlying ``cause`` so operators can quickly tell apart
    "wrong IP / host down" from "wrong port / Redfish disabled" from
    "TLS / DNS" issues.

    Attributes:
        host: The BMC host that failed to connect.
        cause: The underlying transport exception (usually from ``requests``
            / ``urllib3``).
        reason: One of ``"refused"``, ``"unreachable"``, ``"dns"``,
            ``"tls"``, ``"other"`` — a coarse category derived from ``cause``.
    """

    def __init__(self, host: str, cause: Exception = None):
        self.host = host
        self.cause = cause
        self.reason = _classify_connection_cause(cause)
        hint = _connection_hint(host, self.reason)
        super().__init__(
            0,
            f"Unable to connect to host: {host}. Cause: {cause}. {hint}",
        )


class RedfishTimeoutError(RedfishException):
    """
    Raised when a request times out.

    Timeout usually means the BMC accepted the TCP connection but is too slow
    to respond (e.g. mid-collection, or under heavy load). It's distinct from
    :class:`RedfishConnectionError`, which means the TCP handshake itself
    never succeeded.
    """

    def __init__(self, host: str):
        self.host = host
        super().__init__(
            0,
            f"Request timed out connecting to: {host}. "
            f"Hint: the BMC accepted the TCP connection but did not respond "
            f"within the read timeout — it may be busy (e.g. running a "
            f"diagnostic collection) or overloaded. Consider raising "
            f"``read_timeout`` on RedfishClient, or retrying later.",
        )


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


# ---------------------------------------------------------------------------
# Internal helpers for RedfishConnectionError diagnosis
# ---------------------------------------------------------------------------

# Substrings observed in the string form of common transport failures.
# Ordered so the most specific matches win when combined into a single blob.
_CAUSE_MARKERS = (
    ("refused", ("connection refused", "econnrefused", "errno 61", "errno 111")),
    ("unreachable", (
        "no route to host", "network is unreachable", "host is down",
        "ehostunreach", "enetunreach",
    )),
    ("dns", (
        "name or service not known", "nodename nor servname",
        "temporary failure in name resolution", "getaddrinfo failed",
    )),
    ("tls", (
        "ssl", "certificate", "handshake failed", "wrong version number",
    )),
)


def _classify_connection_cause(cause) -> str:
    """
    Categorise a low-level connection failure so callers can display a
    targeted hint. Returns one of: ``refused`` / ``unreachable`` / ``dns``
    / ``tls`` / ``other``.
    """
    if cause is None:
        return "other"
    blob = f"{cause!r} {cause}".lower()
    for reason, markers in _CAUSE_MARKERS:
        for m in markers:
            if m in blob:
                return reason
    return "other"


def _connection_hint(host: str, reason: str) -> str:
    """Return a one-line, action-oriented hint for the given failure reason."""
    if reason == "refused":
        return (
            f"Hint: {host} accepted routing (host is up) but no service is "
            f"listening on the requested TCP port. Check: 1) the IP is a BMC "
            f"address (not a host OS address); 2) the BMC Redfish/HTTPS "
            f"service is enabled; 3) the port matches your RedfishClient "
            f"``scheme``/port (Redfish default is 443 for https)."
        )
    if reason == "unreachable":
        return (
            f"Hint: {host} is not routable from this machine. Check network "
            f"connectivity (VPN / firewall / VLAN / subnet)."
        )
    if reason == "dns":
        return (
            f"Hint: could not resolve host name {host!r}. Check DNS or use "
            f"the raw IP address instead."
        )
    if reason == "tls":
        return (
            f"Hint: TLS/SSL handshake failed with {host}. BMC self-signed "
            f"certificates are expected — RedfishClient defaults to "
            f"``verify_ssl=False``. If you enabled verification, provide a "
            f"trust store; otherwise check the server's TLS version."
        )
    return (
        f"Hint: unclassified connection failure to {host}. Verify basic "
        f"connectivity with ``ping`` / ``nc -zv {host} 443``."
    )
