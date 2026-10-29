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
from .client import CollectionFailure, CollectionResult, RedfishClient
from .exceptions import (
    LogCollectFailedError,
    RedfishAsyncOperationError,
    RedfishAuthError,
    RedfishConnectionError,
    RedfishException,
    RedfishNotFoundError,
    RedfishTimeoutError,
    RedfishValidationError,
    RegistryResolutionError,
)
from .models.common import Condition
from .models.composition import CompositionService, ResourceBlock, ResourceZone
from .models.drive import Drive
from .models.event import Event, EventRecord, EventService, Subscription
from .models.fabric import (
    CXLLogicalDevice,
    Port,
    PortMetrics,
    ResetTransceiversRequest,
)
from .models.logs import Log, LogEntry
from .models.managers import (
    DnsService,
    FirewallRules,
    HttpsCert,
    KvmService,
    LldpService,
    NtpService,
    SecurityService,
    SerialInterface,
    SnmpService,
    SolSourceControlInfo,
    SyslogService,
    VirtualMedia,
    VirtualMediaActions,
    VirtualMediaEjectMediaRequest,
    VirtualMediaHTTPHeaders,
    VirtualMediaInsertMediaAction,
    VirtualMediaInsertMediaRequest,
    VncService,
)
from .models.policy import (
    Policy,
    PolicyCondition,
    PolicyEventResponse,
    PolicyHTTPResponse,
    PolicyResponse,
    PolicyService,
)
from .models.registry import MessageRegistry, RegistryMessage, ResolvedMessage
from .models.resource_key import RedfishResource
from .models.system_resources import (
    MemoryChunks,
    MemoryDomain,
    MemoryMetrics,
    NetworkInterface,
    NetworkPort,
    SecureBoot,
)
from .models.systems import (
    BootOption,
    GraphicalConsoleAction,
    GraphicalConsoleGetOneTimeURLRequest,
    GraphicalConsoleGetOneTimeURLResponse,
    GraphicalConsoleProtocol,
    GraphicalConsoleSetOneTimePasswordRequest,
    GraphicalConsoleSetOneTimePasswordResponse,
    GraphicalConsoleSetPasswordRequest,
    HostGraphicalConsole,
    HTML5Console,
    VNCConsole,
)
from .models.task import AsyncOperationResult, TaskRecoveryPolicy
from .models.telemetry import MetricDefinition, MetricReport, MetricReportDefinition, TelemetryService, Triggers
from .models.update import (
    FirmwareUpdateResponse,
    SoftwareInventory,
    UpdateParameters,
    UpdateServiceCapabilities,
)

__version__ = "1.3.1"
__author__ = "RedNote Infrastructure"

__all__ = [
    "RedfishClient",
    "CollectionFailure",
    "CollectionResult",
    "TelemetryService",
    "MetricDefinition",
    "MetricReportDefinition",
    "MetricReport",
    "Triggers",
    "RedfishResource",
    "RedfishException",
    "RedfishNotFoundError",
    "RedfishAuthError",
    "RedfishConnectionError",
    "RedfishTimeoutError",
    "RedfishValidationError",
    "RegistryResolutionError",
    "LogCollectFailedError",
    "RedfishAsyncOperationError",
    "TaskRecoveryPolicy",
    "AsyncOperationResult",
    # Models commonly used at API boundary.
    "BootOption",
    "GraphicalConsoleAction",
    "GraphicalConsoleGetOneTimeURLRequest",
    "GraphicalConsoleGetOneTimeURLResponse",
    "GraphicalConsoleProtocol",
    "GraphicalConsoleSetOneTimePasswordRequest",
    "GraphicalConsoleSetOneTimePasswordResponse",
    "GraphicalConsoleSetPasswordRequest",
    "HostGraphicalConsole",
    "HTML5Console",
    "VNCConsole",
    "CompositionService",
    "Condition",
    "ResourceBlock",
    "ResourceZone",
    "DnsService",
    "Drive",
    "Policy",
    "PolicyCondition",
    "PolicyEventResponse",
    "PolicyHTTPResponse",
    "PolicyResponse",
    "PolicyService",
    "FirmwareUpdateResponse",
    "SoftwareInventory",
    "UpdateParameters",
    "UpdateServiceCapabilities",
    "EventService",
    "Event",
    "EventRecord",
    "Port",
    "PortMetrics",
    "CXLLogicalDevice",
    "ResetTransceiversRequest",
    "FirewallRules",
    "HttpsCert",
    "KvmService",
    "LldpService",
    "Log",
    "LogEntry",
    "MessageRegistry",
    "RegistryMessage",
    "ResolvedMessage",
    "NtpService",
    "SecurityService",
    "SnmpService",
    "SolSourceControlInfo",
    "SerialInterface",
    "Subscription",
    "SecureBoot",
    "NetworkInterface",
    "NetworkPort",
    "MemoryDomain",
    "MemoryChunks",
    "MemoryMetrics",
    "SyslogService",
    "VirtualMedia",
    "VirtualMediaActions",
    "VirtualMediaEjectMediaRequest",
    "VirtualMediaHTTPHeaders",
    "VirtualMediaInsertMediaAction",
    "VirtualMediaInsertMediaRequest",
    "VncService",
]
