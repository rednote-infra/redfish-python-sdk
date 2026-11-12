"""Host-specific warning policy for explicitly unverified BMC connections."""
import re
import warnings
from urllib.parse import urlsplit

from .exceptions import RedfishValidationError

_TLS_WARNING_MODULE = r"urllib3\.connectionpool$"


def configure_tls_warnings(host: str, verify, suppress: bool) -> None:
    """Set the process-wide unverified-warning policy for this BMC hostname.

    Python warning filters are process-wide: clients for the same hostname share
    the most recently configured policy. Verified connections do not alter it.
    Other warning messages and TLS exceptions are unaffected.
    """
    if not isinstance(suppress, bool):
        raise RedfishValidationError("suppress_insecure_warnings must be a boolean")
    if verify:
        return
    hostname = urlsplit(f"https://{host}").hostname
    warnings.filterwarnings(
        "ignore" if suppress else "default",
        message=rf"Unverified HTTPS request is being made to host '{re.escape(hostname)}'\.",
        module=_TLS_WARNING_MODULE,
    )
