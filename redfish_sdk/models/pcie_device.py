"""
PCIe Device component models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status


class PCIeInterface(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    lanes_in_use: Optional[int] = Field(None, alias="LanesInUse")
    max_lanes: Optional[int] = Field(None, alias="MaxLanes")
    max_pcie_type: Optional[str] = Field(None, alias="MaxPCIeType")
    pcie_type: Optional[str] = Field(None, alias="PCIeType")


class GpuCore(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    build_time: Optional[str] = Field(None, alias="BuildTime")
    capacity_gb: Optional[int] = Field(None, alias="CapacityGB")
    member_id: Optional[int] = Field(None, alias="MemberId")
    power: Optional[float] = Field(None, alias="Power")
    temperature: Optional[int] = Field(None, alias="Temperature")


class GpuPerformanceParameters(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    encoder_usage_percent: Optional[str] = Field(None, alias="EncoderUsagePercent")
    decoder_usage_percent: Optional[str] = Field(None, alias="DecoderUsagePercent")
    gpu_usage_percent: Optional[str] = Field(None, alias="GPUUsagePercent")
    temperature_celsius: Optional[str] = Field(None, alias="TemperatureCelsius")
    power_watts: Optional[str] = Field(None, alias="PowerWatts")


class PCIeDeviceOEMPublic(BaseModel):
    """OEM public extension for PCIe GPU devices (华为 xFusion specific)."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    device_bdf: Optional[str] = Field(None, alias="DeviceBDF")
    device_locator: Optional[str] = Field(None, alias="DeviceLocator")
    memory_size_mib: Optional[int] = Field(None, alias="MemorySizeMiB")
    gpu_core: Optional[List[GpuCore]] = Field(None, alias="GpuCore")
    gpu_performance_parameters: Optional[GpuPerformanceParameters] = Field(
        None, alias="GpuPerformanceParameters"
    )
    memory_band_width: Optional[str] = Field(None, alias="MemoryBandWidth")
    reading_celsius: Optional[int] = Field(None, alias="ReadingCelsius")
    link_speed: Optional[str] = Field(None, alias="LinkSpeed")
    max_link_speed: Optional[str] = Field(None, alias="MaxLinkSpeed")
    link_width: Optional[int] = Field(None, alias="LinkWidth")
    max_link_width: Optional[int] = Field(None, alias="MaxLinkWidth")
    pcie_card_type: Optional[str] = Field(None, alias="PCIeCardType")
    power_capacity_watts: Optional[int] = Field(None, alias="PowerCapacityWatts")
    power_watts: Optional[float] = Field(None, alias="PowerWatts")
    power_consumed_watts: Optional[float] = Field(None, alias="PowerConsumedWatts")
    slot_number: Optional[int] = Field(None, alias="SlotNumber")


class PCIeDeviceOEM(BaseModel):
    """OEM wrapper for PCIe device."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    gpu_oem_public: Optional[PCIeDeviceOEMPublic] = Field(None, alias="Public")


class PCIeDevice(Entity):
    """
    Represents a PCIe device (GPU, NIC, etc.).
    Endpoint: /redfish/v1/Chassis/{chassisId}/PCIeDevices/{pcieDeviceId}

    The 'name' field is used to identify GPU devices (contains "GPU" substring).
    OEM field contains extended GPU metrics for 华为 xFusion servers.

    """
    card_model: Optional[str] = Field(None, alias="CardModel")
    pcie_functions: Optional[Link] = Field(None, alias="PCIeFunctions")
    pcie_interface: Optional[PCIeInterface] = Field(None, alias="PCIeInterface")
    oem: Optional[PCIeDeviceOEM] = Field(None, alias="Oem")
    staged_version: Optional[str] = Field(None, alias="StagedVersion")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    model: Optional[str] = Field(None, alias="Model", validate="type=str")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="type=str")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    firmware_version: Optional[str] = Field(None, alias="FirmwareVersion", validate="type=str")
