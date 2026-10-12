"""Optional SecureBoot, network port, and memory topology resource models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .actions import ActionDescriptor, ActionMap
from .common import Entity, Link, Status


class OptionalSystemResource(Entity):
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")
    status: Optional[Status] = Field(None, alias="Status")


class ResetKeysAction(ActionDescriptor):
    reset_keys_type_allowable_values: Optional[List[str]] = Field(None, alias="ResetKeysType@Redfish.AllowableValues")


class SecureBootActions(ActionMap):
    reset_keys: Optional[ResetKeysAction] = Field(None, alias="#SecureBoot.ResetKeys")

    @field_validator("reset_keys", mode="before")
    @classmethod
    def valid_descriptor(cls, value: Any) -> Any:
        return value if isinstance(value, (dict, ResetKeysAction)) else None


class ResetKeysRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reset_keys_type: str = Field(..., alias="ResetKeysType")


class SecureBoot(OptionalSystemResource):
    actions: Optional[SecureBootActions] = Field(None, alias="Actions")
    secure_boot_enable: Optional[bool] = Field(None, alias="SecureBootEnable")
    secure_boot_current_boot: Optional[str] = Field(None, alias="SecureBootCurrentBoot")
    secure_boot_mode: Optional[str] = Field(None, alias="SecureBootMode")
    secure_boot_databases: Optional[Link] = Field(None, alias="SecureBootDatabases")


class SecureBootPatch(Entity):
    odata_etag: Optional[str] = Field(None, alias="@odata.etag", exclude=True)
    secure_boot_enable: bool = Field(..., alias="SecureBootEnable")


class NetworkInterfaceLinks(Entity):
    network_adapter: Optional[Link] = Field(None, alias="NetworkAdapter")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class NetworkInterface(OptionalSystemResource):
    network_ports: Optional[Link] = Field(None, alias="NetworkPorts")
    network_device_functions: Optional[Link] = Field(None, alias="NetworkDeviceFunctions")
    ports: Optional[Link] = Field(None, alias="Ports")
    links: Optional[NetworkInterfaceLinks] = Field(None, alias="Links")


class SupportedLinkCapability(Entity):
    auto_speed_negotiation: Optional[bool] = Field(None, alias="AutoSpeedNegotiation")
    capable_link_speed_mbps: Optional[float] = Field(None, alias="CapableLinkSpeedMbps")
    link_speed_mbps: Optional[float] = Field(None, alias="LinkSpeedMbps")
    link_network_technology: Optional[str] = Field(None, alias="LinkNetworkTechnology")


class NetworkPort(OptionalSystemResource):
    active_link_technology: Optional[str] = Field(None, alias="ActiveLinkTechnology")
    associated_network_addresses: Optional[List[str]] = Field(None, alias="AssociatedNetworkAddresses")
    current_link_speed_mbps: Optional[float] = Field(None, alias="CurrentLinkSpeedMbps")
    link_status: Optional[str] = Field(None, alias="LinkStatus")
    physical_port_number: Optional[str] = Field(None, alias="PhysicalPortNumber")
    signal_detected: Optional[bool] = Field(None, alias="SignalDetected")
    max_frame_size: Optional[int] = Field(None, alias="MaxFrameSize")
    port_maximum_mtu: Optional[int] = Field(None, alias="PortMaximumMTU")
    flow_control_configuration: Optional[str] = Field(None, alias="FlowControlConfiguration")
    flow_control_status: Optional[str] = Field(None, alias="FlowControlStatus")
    supported_ethernet_capabilities: Optional[List[str]] = Field(None, alias="SupportedEthernetCapabilities")
    supported_link_capabilities: Optional[List[SupportedLinkCapability]] = Field(None, alias="SupportedLinkCapabilities")
    wake_on_lan_enabled: Optional[bool] = Field(None, alias="WakeOnLANEnabled")
    eee_enabled: Optional[bool] = Field(None, alias="EEEEnabled")
    fc_fabric_name: Optional[str] = Field(None, alias="FCFabricName")
    fc_port_connection_type: Optional[str] = Field(None, alias="FCPortConnectionType")
    number_discovered_remote_ports: Optional[int] = Field(None, alias="NumberDiscoveredRemotePorts")
    vendor_id: Optional[str] = Field(None, alias="VendorId")
    net_dev_func_max_bw_alloc: Optional[List[Dict[str, Any]]] = Field(None, alias="NetDevFuncMaxBWAlloc")
    net_dev_func_min_bw_alloc: Optional[List[Dict[str, Any]]] = Field(None, alias="NetDevFuncMinBWAlloc")


class InterleavableMemorySet(Entity):
    memory_set: Optional[List[Link]] = Field(None, alias="MemorySet")


class MemoryDomain(OptionalSystemResource):
    allows_memory_chunk_creation: Optional[bool] = Field(None, alias="AllowsMemoryChunkCreation")
    allows_block_provisioning: Optional[bool] = Field(None, alias="AllowsBlockProvisioning")
    allows_mirroring: Optional[bool] = Field(None, alias="AllowsMirroring")
    allows_sparing: Optional[bool] = Field(None, alias="AllowsSparing")
    interleavable_memory_sets: Optional[List[InterleavableMemorySet]] = Field(None, alias="InterleavableMemorySets")
    memory_chunks: Optional[Link] = Field(None, alias="MemoryChunks")


class MemoryInterleaveSet(Entity):
    memory: Optional[Link] = Field(None, alias="Memory")
    memory_level: Optional[int] = Field(None, alias="MemoryLevel")
    offset_mib: Optional[int] = Field(None, alias="OffsetMiB")
    size_mib: Optional[int] = Field(None, alias="SizeMiB")
    region_id: Optional[str] = Field(None, alias="RegionId")


class MemoryChunks(OptionalSystemResource):
    address_range_offset_mib: Optional[int] = Field(None, alias="AddressRangeOffsetMiB")
    address_range_type: Optional[str] = Field(None, alias="AddressRangeType")
    memory_chunk_size_mib: Optional[int] = Field(None, alias="MemoryChunkSizeMiB")
    is_mirror_enabled: Optional[bool] = Field(None, alias="IsMirrorEnabled")
    is_spare: Optional[bool] = Field(None, alias="IsSpare")
    interleave_sets: Optional[List[MemoryInterleaveSet]] = Field(None, alias="InterleaveSets")
    links: Optional[Dict[str, Any]] = Field(None, alias="Links")


class MemoryPeriod(Entity):
    blocks_read: Optional[int] = Field(None, alias="BlocksRead")
    blocks_written: Optional[int] = Field(None, alias="BlocksWritten")


class MemoryAlarmTrips(Entity):
    address_parity_error: Optional[bool] = Field(None, alias="AddressParityError")
    correctable_ecc_error: Optional[bool] = Field(None, alias="CorrectableECCError")
    uncorrectable_ecc_error: Optional[bool] = Field(None, alias="UncorrectableECCError")
    spare_block: Optional[bool] = Field(None, alias="SpareBlock")
    temperature: Optional[bool] = Field(None, alias="Temperature")


class MemoryHealthData(Entity):
    alarm_trips: Optional[MemoryAlarmTrips] = Field(None, alias="AlarmTrips")
    data_loss_detected: Optional[bool] = Field(None, alias="DataLossDetected")
    last_shutdown_success: Optional[bool] = Field(None, alias="LastShutdownSuccess")
    performance_degraded: Optional[bool] = Field(None, alias="PerformanceDegraded")
    predicted_media_life_left_percent: Optional[float] = Field(None, alias="PredictedMediaLifeLeftPercent")
    remaining_spare_block_percentage: Optional[float] = Field(None, alias="RemainingSpareBlockPercentage")


class MemoryMetrics(OptionalSystemResource):
    bandwidth_percent: Optional[float] = Field(None, alias="BandwidthPercent")
    block_size_bytes: Optional[int] = Field(None, alias="BlockSizeBytes")
    current_period: Optional[MemoryPeriod] = Field(None, alias="CurrentPeriod")
    life_time: Optional[MemoryPeriod] = Field(None, alias="LifeTime")
    health_data: Optional[MemoryHealthData] = Field(None, alias="HealthData")
    operating_speed_mhz: Optional[int] = Field(None, alias="OperatingSpeedMHz")
