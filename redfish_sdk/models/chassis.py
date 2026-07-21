"""
Chassis resource models.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link, Status
from .drive import Drive, Location  # noqa: F401
from .network_adapter import (  # noqa: F401
    NPAR,
    Controller,
    ControllerCapabilities,
    DataCenterBridging,
    NetworkAdapter,
    VirtualFunction,
    VirtualizationOffload,
)
from .oem import Oem
from .pcie_device import (  # noqa: F401
    GpuCore,
    GpuPerformanceParameters,
    PCIeDevice,
    PCIeDeviceOEM,
    PCIeDeviceOEMPublic,
    PCIeInterface,
)
from .power import (  # noqa: F401
    InputRange,
    Power,
    PowerControl,
    PowerSupply,
    Voltage,
)

# ---------------------------------------------------------------------------
# Re-export component models for backward compatibility
# ---------------------------------------------------------------------------
from .thermal import Fan, Redundancy, Temperature, Thermal  # noqa: F401

# ---------------------------------------------------------------------------
# Chassis
# ---------------------------------------------------------------------------

class ChassisLinks(BaseModel):
    """Links section within a Chassis resource."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    drives: Optional[List[Link]] = Field(None, alias="Drives")
    pcie_devices: Optional[List[Link]] = Field(None, alias="PCIeDevices")
    managed_by: Optional[List[Link]] = Field(None, alias="ManagedBy")
    contains: Optional[List[Link]] = Field(None, alias="Contains")
    contained_by: Optional[Link] = Field(None, alias="ContainedBy")
    computer_systems: Optional[List[Link]] = Field(None, alias="ComputerSystems")


class Chassis(Entity):
    """
    Represents a physical chassis (server enclosure).
    Endpoint: /redfish/v1/Chassis/{chassisId}

    """
    uuid: Optional[str] = Field(None, alias="UUID")
    links: Optional[ChassisLinks] = Field(None, alias="Links")
    asset_tag: Optional[str] = Field(None, alias="AssetTag")
    chassis_type: Optional[str] = Field(None, alias="ChassisType")
    depth_mm: Optional[float] = Field(None, alias="DepthMm")
    height_mm: Optional[float] = Field(None, alias="HeightMm")
    indicator_led: Optional[str] = Field(None, alias="IndicatorLED")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    model: Optional[str] = Field(None, alias="Model")
    drives: Optional[Link] = Field(None, alias="Drives")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    power: Optional[Link] = Field(None, alias="Power")
    power_state: Optional[str] = Field(None, alias="PowerState")
    sku: Optional[str] = Field(None, alias="SKU")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    status: Optional[Status] = Field(None, alias="Status")
    thermal: Optional[Link] = Field(None, alias="Thermal")
    weight_kg: Optional[float] = Field(None, alias="WeightKg")
    width_mm: Optional[float] = Field(None, alias="WidthMm")
    pcie_devices: Optional[Link] = Field(None, alias="PCIeDevices")
    network_adapters: Optional[Link] = Field(None, alias="NetworkAdapters")
    sensors: Optional[Link] = Field(None, alias="Sensors")
    oem: Optional[Oem] = Field(None, alias="Oem")
