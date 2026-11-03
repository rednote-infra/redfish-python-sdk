"""Authentication types used by the Redfish SDK."""

from enum import Enum


class AuthenticationMode(str, Enum):
    """Supported authentication modes for Redfish requests."""

    BASIC = "basic"
    SESSION = "session"
