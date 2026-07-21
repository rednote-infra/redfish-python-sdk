"""
Memory (DIMM) component models.

"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status
from .oem import Oem


class MemoryLocation(BaseModel):
    """Physical location info for a memory module."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    channel: Optional[Any] = Field(None, alias="Channel")
    memory_controller: Optional[int] = Field(None, alias="MemoryController")
    slot: Optional[int] = Field(None, alias="Slot")
    socket: Optional[int] = Field(None, alias="Socket")


class Memory(Entity):
    """
    Represents a memory module (DIMM).
    Endpoint: /redfish/v1/Systems/{systemId}/Memory/{memoryId}

    """
    base_module_type: Optional[str] = Field(None, alias="BaseModuleType")
    bus_width_bits: Optional[int] = Field(None, alias="BusWidthBits")
    capacity_mib: Optional[int] = Field(None, alias="CapacityMiB", validate="required,type=int,gt=0")
    data_width_bits: Optional[int] = Field(None, alias="DataWidthBits")
    operating_speed_mhz: Optional[int] = Field(None, alias="OperatingSpeedMhz", validate="type=int,gt=0")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="type=str")
    vendor_id: Optional[str] = Field(None, alias="VendorID")
    part_number: Optional[str] = Field(None, alias="PartNumber", validate="type=str")
    serial_number: Optional[str] = Field(None, alias="SerialNumber", validate="type=str")
    device_locator: Optional[str] = Field(None, alias="DeviceLocator")
    device_id: Optional[str] = Field(None, alias="DeviceID")
    error_correction: Optional[str] = Field(None, alias="ErrorCorrection")
    memory_device_type: Optional[str] = Field(None, alias="MemoryDeviceType", validate="type=str")
    memory_type: Optional[str] = Field(None, alias="MemoryType")
    rank_count: Optional[int] = Field(None, alias="RankCount")
    memory_location: Optional[MemoryLocation] = Field(None, alias="MemoryLocation")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    oem: Optional[Oem] = Field(None, alias="Oem")
    environment_metrics: Optional[Link] = Field(None, alias="EnvironmentMetrics")
