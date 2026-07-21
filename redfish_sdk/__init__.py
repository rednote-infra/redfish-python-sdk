"""
Redfish Python SDK

A Python SDK for interacting with Redfish-compliant BMC (Baseboard Management Controller)
endpoints.

Quick start:
    import os
    from redfish_sdk import RedfishClient

    # Credentials are read from environment variables:
    #   export BMC_IP="<bmc-ip>"
    #   export BMC_USER="<bmc-user>"
    #   export BMC_PASSWORD="<bmc-password>"
    client = RedfishClient(
        host=os.environ["BMC_IP"],
        username=os.environ["BMC_USER"],
        password=os.environ["BMC_PASSWORD"],
    )

    # Get system information
    system = client.get_system()
    print(f"System: {system.manufacturer} {system.model}")
    print(f"Power: {system.power_state}")
    print(f"SN: {system.serial_number}")

    client.close()
"""
from .client import RedfishClient
from .exceptions import (
    RedfishAuthError,
    RedfishConnectionError,
    RedfishException,
    RedfishNotFoundError,
    RedfishTimeoutError,
    RedfishValidationError,
)
from .models.drive import Drive
from .models.event import EventService, Subscription
from .models.logs import Log, LogEntry
from .models.resource_key import RedfishResource
from .models.systems import BootOption

__version__ = "1.0.0"
__author__ = "RedNote Infrastructure"

__all__ = [
    "RedfishClient",
    "RedfishResource",
    "RedfishException",
    "RedfishNotFoundError",
    "RedfishAuthError",
    "RedfishConnectionError",
    "RedfishTimeoutError",
    "RedfishValidationError",
    # Models commonly used at API boundary.
    "BootOption",
    "Drive",
    "EventService",
    "Log",
    "LogEntry",
    "Subscription",
]
