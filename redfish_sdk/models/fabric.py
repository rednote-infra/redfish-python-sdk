"""Read-only models for optional Redfish CXL and UALink topology."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link, Status
from .storage import Identifier


class ProcessorUALink(BaseModel):
    """UALink identity and supported accelerator range for a processor."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    accelerator_id: Optional[int] = Field(None, alias="AcceleratorID")
    max_supported_accelerator_id: Optional[int] = Field(
        None, alias="MaxSupportedAcceleratorID"
    )


class ProcessorLinks(BaseModel):
    """Topology links advertised by a Processor resource."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    connected_processors: Optional[List[Link]] = Field(
        None, alias="ConnectedProcessors"
    )
    endpoints: Optional[List[Link]] = Field(None, alias="Endpoints")
    fabric_adapters: Optional[List[Link]] = Field(None, alias="FabricAdapters")
    pcie_device: Optional[Link] = Field(None, alias="PCIeDevice")
    pcie_functions: Optional[List[Link]] = Field(None, alias="PCIeFunctions")


class CXLTelemetryCapabilities(BaseModel):
    """CXL QoS telemetry capabilities."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    egress_port_backpressure_supported: Optional[bool] = Field(
        None, alias="EgressPortBackpressureSupported"
    )
    temporary_throughput_reduction_supported: Optional[bool] = Field(
        None, alias="TemporaryThroughputReductionSupported"
    )


class PortCXLCongestion(BaseModel):
    """CXL egress congestion reporting and thresholds for a port."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    backpressure_sample_interval: Optional[int] = Field(
        None, alias="BackpressureSampleInterval"
    )
    completion_collection_interval: Optional[int] = Field(
        None, alias="CompletionCollectionInterval"
    )
    congestion_telemetry_enabled: Optional[bool] = Field(
        None, alias="CongestionTelemetryEnabled"
    )
    egress_moderate_percentage: Optional[int] = Field(
        None, alias="EgressModeratePercentage"
    )
    egress_severe_percentage: Optional[int] = Field(
        None, alias="EgressSeverePercentage"
    )
    max_sustained_request_cmp_bias: Optional[int] = Field(
        None, alias="MaxSustainedRequestCmpBias"
    )


class PortCXL(BaseModel):
    """CXL capabilities and current state for a Port resource."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    congestion: Optional[PortCXLCongestion] = Field(None, alias="Congestion")
    connected_device_mode: Optional[str] = Field(None, alias="ConnectedDeviceMode")
    connected_device_type: Optional[str] = Field(None, alias="ConnectedDeviceType")
    current_port_configuration_state: Optional[str] = Field(
        None, alias="CurrentPortConfigurationState"
    )
    max_logical_device_count: Optional[int] = Field(
        None, alias="MaxLogicalDeviceCount"
    )
    qos_telemetry_capabilities: Optional[CXLTelemetryCapabilities] = Field(
        None, alias="QoSTelemetryCapabilities"
    )
    supported_cxl_modes: Optional[List[str]] = Field(None, alias="SupportedCXLModes")
    temporary_throughput_reduction_enabled: Optional[bool] = Field(
        None, alias="TemporaryThroughputReductionEnabled"
    )


class PortUALink(BaseModel):
    """UALink capabilities and current protocol-layer state for a port."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    authentication_mode_enabled: Optional[bool] = Field(
        None, alias="AuthenticationModeEnabled"
    )
    dl_down_delay_milliseconds: Optional[int] = Field(
        None, alias="DLDownDelayMilliseconds"
    )
    dl_state: Optional[str] = Field(None, alias="DLState")
    generation: Optional[str] = Field(None, alias="Generation")
    link_folding_enabled: Optional[bool] = Field(None, alias="LinkFoldingEnabled")
    link_folding_supported: Optional[bool] = Field(
        None, alias="LinkFoldingSupported"
    )
    link_resiliency_enabled: Optional[bool] = Field(
        None, alias="LinkResiliencyEnabled"
    )
    link_resiliency_supported: Optional[bool] = Field(
        None, alias="LinkResiliencySupported"
    )
    non_strict_ordering_mode_enabled: Optional[bool] = Field(
        None, alias="NonStrictOrderingModeEnabled"
    )
    pldl_admin_enabled: Optional[bool] = Field(None, alias="PLDLAdminEnabled")
    pl_state: Optional[str] = Field(None, alias="PLState")
    tl_state: Optional[str] = Field(None, alias="TLState")
    tlupli_admin_enabled: Optional[bool] = Field(None, alias="TLUPLIAdminEnabled")
    tx_ack_timeout_nanoseconds: Optional[int] = Field(
        None, alias="TXAckTimeoutNanoseconds"
    )
    ualink_128g_extended_speed_mode: Optional[str] = Field(
        None, alias="UALink128GExtendedSpeedMode"
    )
    ualink_200g_codeword_interleave: Optional[str] = Field(
        None, alias="UALink200GCodewordInterleave"
    )
    ualink_200g_serial_rate: Optional[str] = Field(
        None, alias="UALink200GSerialRate"
    )
    uart_admin_enabled: Optional[bool] = Field(None, alias="UARTAdminEnabled")
    upli_completer_state: Optional[str] = Field(None, alias="UPLICompleterState")
    upli_originator_state: Optional[str] = Field(None, alias="UPLIOriginatorState")
    upli_watchdog_timer_microseconds: Optional[int] = Field(
        None, alias="UPLIWatchdogTimerMicroseconds"
    )


class PortLinks(BaseModel):
    """Related resources advertised by a Port."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    associated_endpoints: Optional[List[Link]] = Field(
        None, alias="AssociatedEndpoints"
    )
    associated_physical_ports: Optional[List[Link]] = Field(
        None, alias="AssociatedPhysicalPorts"
    )
    cxl_logical_devices: Optional[List[Link]] = Field(
        None, alias="CXLLogicalDevices"
    )
    connected_ports: Optional[List[Link]] = Field(None, alias="ConnectedPorts")
    connected_switch_ports: Optional[List[Link]] = Field(
        None, alias="ConnectedSwitchPorts"
    )
    connected_switches: Optional[List[Link]] = Field(
        None, alias="ConnectedSwitches"
    )
    ethernet_interfaces: Optional[List[Link]] = Field(
        None, alias="EthernetInterfaces"
    )


class Port(Entity):
    """A generic Redfish Port, including optional CXL and UALink data."""

    active_width: Optional[int] = Field(None, alias="ActiveWidth")
    capable_protocol_versions: Optional[List[str]] = Field(
        None, alias="CapableProtocolVersions"
    )
    configured_speed_gbps: Optional[float] = Field(None, alias="ConfiguredSpeedGbps")
    configured_width: Optional[int] = Field(None, alias="ConfiguredWidth")
    current_protocol_version: Optional[str] = Field(
        None, alias="CurrentProtocolVersion"
    )
    current_speed_gbps: Optional[float] = Field(None, alias="CurrentSpeedGbps")
    cxl: Optional[PortCXL] = Field(None, alias="CXL")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    interface_enabled: Optional[bool] = Field(None, alias="InterfaceEnabled")
    link_network_technology: Optional[str] = Field(
        None, alias="LinkNetworkTechnology"
    )
    link_state: Optional[str] = Field(None, alias="LinkState")
    link_status: Optional[str] = Field(None, alias="LinkStatus")
    links: Optional[PortLinks] = Field(None, alias="Links")
    max_speed_gbps: Optional[float] = Field(None, alias="MaxSpeedGbps")
    metrics: Optional[Link] = Field(None, alias="Metrics")
    port_id: Optional[str] = Field(None, alias="PortId")
    port_medium: Optional[str] = Field(None, alias="PortMedium")
    port_protocol: Optional[str] = Field(None, alias="PortProtocol")
    port_type: Optional[str] = Field(None, alias="PortType")
    status: Optional[Status] = Field(None, alias="Status")
    ualink: Optional[PortUALink] = Field(None, alias="UALink")
    width: Optional[int] = Field(None, alias="Width")


class PortMetricsCXL(BaseModel):
    """CXL-specific counters in PortMetrics."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    backpressure_average_percentage: Optional[float] = Field(
        None, alias="BackpressureAveragePercentage"
    )


class PortMetrics(Entity):
    """Traffic, error, and CXL metrics for a Port."""

    cxl: Optional[PortMetricsCXL] = Field(None, alias="CXL")
    rx_bytes: Optional[int] = Field(None, alias="RXBytes")
    rx_errors: Optional[int] = Field(None, alias="RXErrors")
    tx_bytes: Optional[int] = Field(None, alias="TXBytes")
    tx_errors: Optional[int] = Field(None, alias="TXErrors")


class CXLLogicalDeviceLinks(BaseModel):
    """Topology links advertised by a CXLLogicalDevice."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    endpoints: Optional[List[Link]] = Field(None, alias="Endpoints")
    memory_chunks: Optional[List[Link]] = Field(None, alias="MemoryChunks")
    memory_domains: Optional[List[Link]] = Field(None, alias="MemoryDomains")
    pcie_functions: Optional[List[Link]] = Field(None, alias="PCIeFunctions")
    port: Optional[Link] = Field(None, alias="Port")


class CXLLogicalDeviceQoS(BaseModel):
    """Current QoS allocation for a CXL logical device."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    allocated_bandwidth: Optional[int] = Field(None, alias="AllocatedBandwidth")
    limit_percent: Optional[int] = Field(None, alias="LimitPercent")


class CXLLogicalDevice(Entity):
    """A CXL logical device discovered from an advertised collection or link."""

    available_extents: Optional[int] = Field(None, alias="AvailableExtents")
    available_tags: Optional[int] = Field(None, alias="AvailableTags")
    identifiers: Optional[List[Identifier]] = Field(None, alias="Identifiers")
    links: Optional[CXLLogicalDeviceLinks] = Field(None, alias="Links")
    log: Optional[Link] = Field(None, alias="Log")
    memory_regions: Optional[Link] = Field(None, alias="MemoryRegions")
    memory_size_mib: Optional[int] = Field(None, alias="MemorySizeMiB")
    qos: Optional[CXLLogicalDeviceQoS] = Field(None, alias="QoS")
    qos_telemetry_capabilities: Optional[CXLTelemetryCapabilities] = Field(
        None, alias="QoSTelemetryCapabilities"
    )
    semantics_supported: Optional[List[str]] = Field(
        None, alias="SemanticsSupported"
    )
    status: Optional[Status] = Field(None, alias="Status")
    total_supported_extents: Optional[int] = Field(
        None, alias="TotalSupportedExtents"
    )
    total_supported_tags: Optional[int] = Field(None, alias="TotalSupportedTags")
