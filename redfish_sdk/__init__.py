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
from .auth import AuthenticationMode
from .client import CollectionFailure, CollectionResult, RedfishClient
from .exceptions import (
    LogCollectFailedError,
    RedfishAsyncOperationError,
    RedfishAuthError,
    RedfishBadRequestError,
    RedfishConflictError,
    RedfishConnectionError,
    RedfishException,
    RedfishMissingAttributeError,
    RedfishNotFoundError,
    RedfishPasswordChangeRequiredError,
    RedfishPreconditionFailedError,
    RedfishRateLimitError,
    RedfishServiceUnavailableError,
    RedfishTimeoutError,
    RedfishValidationError,
    RegistryResolutionError,
)
from .models.attribute_registry import (
    AttributeDefinition,
    AttributeDependency,
    AttributeDependencyMap,
    AttributeMapFrom,
    AttributeMenu,
    AttributeRegistry,
    AttributeRegistryEntries,
    AttributeType,
    AttributeValue,
)
from .models.common import Condition
from .models.composition import CompositionService, ResourceBlock, ResourceZone
from .models.cooling import Fan as StandaloneFan
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
from .models.power import PowerSubsystem, PowerSupply, PowerSupplyMetrics
from .models.registry import MessageRegistry, RegistryMessage, ResolvedMessage
from .models.resource_key import RedfishResource
from .models.settings import (
    ApplyTime,
    MaintenanceWindow,
    OperationApplyTime,
    OperationApplyTimeSupport,
    Settings,
    SettingsApplyTime,
)
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
from .oem import OemCategory, OemProviderConflictError, OemProviderLoadError, OemProviderRegistry
from .request import HttpMethod
from .response import GenericResponse
from .retry import RetryPolicy

__version__ = "1.3.1"
__author__ = "RedNote Infrastructure"

__all__ = [
    "HttpMethod",
    "OemCategory", "OemProviderRegistry", "OemProviderLoadError", "OemProviderConflictError",
    "AttributeRegistry", "AttributeRegistryEntries", "AttributeDefinition", "AttributeType", "AttributeValue",
    "AttributeMenu", "AttributeDependency", "AttributeDependencyMap", "AttributeMapFrom",
    "ApplyTime", "MaintenanceWindow", "OperationApplyTime", "OperationApplyTimeSupport", "Settings", "SettingsApplyTime",
    "AuthenticationMode",
    "RetryPolicy",
    "GenericResponse",
    "RedfishClient",
    "RedfishMissingAttributeError",
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
    "RedfishBadRequestError",
    "RedfishConflictError",
    "RedfishPasswordChangeRequiredError",
    "RedfishPreconditionFailedError",
    "RedfishRateLimitError",
    "RedfishServiceUnavailableError",
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
    "StandaloneFan",
    "Policy",
    "PolicyCondition",
    "PolicyEventResponse",
    "PolicyHTTPResponse",
    "PolicyResponse",
    "PolicyService",
    "PowerSubsystem",
    "PowerSupply",
    "PowerSupplyMetrics",
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
