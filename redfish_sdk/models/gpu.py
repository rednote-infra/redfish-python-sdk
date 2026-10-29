"""
GPU (Graphics Processing Unit) component models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField

from .check import Field
from .common import Entity, Link


class GpuLinks(BaseModel):
    """Standard topology links advertised by a graphics controller."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    pcie_device: Optional[Link] = Field(None, alias="PCIeDevice")
    pcie_functions: Optional[List[Link]] = Field(None, alias="PCIeFunctions")
    processors: Optional[List[Link]] = Field(None, alias="Processors")


class PCIeFunctionLinks(BaseModel):
    """Topology links advertised by a PCIe function."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    pcie_device: Optional[Link] = Field(None, alias="PCIeDevice")
    processor: Optional[Link] = Field(None, alias="Processor")


class PCIeFunction(Entity):
    """Subset of PCIeFunction used for accelerator discovery."""
    device_class: Optional[str] = Field(None, alias="DeviceClass")
    function_id: Optional[int] = Field(None, alias="FunctionId")
    links: Optional[PCIeFunctionLinks] = Field(None, alias="Links")


class AccelerationFunctionLinks(BaseModel):
    """Topology links advertised by an acceleration function."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    pcie_functions: Optional[List[Link]] = Field(None, alias="PCIeFunctions")


class AccelerationFunction(Entity):
    """Subset of AccelerationFunction used for GPU discovery."""
    acceleration_function_type: Optional[str] = Field(
        None, alias="AccelerationFunctionType"
    )
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    power_watts: Optional[int] = Field(None, alias="PowerWatts")
    version: Optional[str] = Field(None, alias="Version")
    links: Optional[AccelerationFunctionLinks] = Field(None, alias="Links")


class GpuOEM(BaseModel):
    """OEM-specific GPU fields."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    serial_number: Optional[str] = Field(None, alias="SerialNumber")


class Gpu(Entity):
    """
    Represents a GPU (Graphics Processing Unit).
    Can come from either /redfish/v1/Systems/{systemId}/GraphicsControllers
    or derived from /redfish/v1/Chassis/{chassisId}/PCIeDevices.

    """
    manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="type=str")
    model: Optional[str] = Field(None, alias="Model", validate="type=str")
    version: Optional[str] = Field(None, alias="Version", validate="type=str")
    power_watts: Optional[str] = Field(None, alias="PowerWatts", validate="type=str")
    oem: Optional[GpuOEM] = Field(None, alias="Oem")
    links: Optional[GpuLinks] = Field(None, alias="Links")

    # SDK discovery metadata, excluded from Redfish serialization.
    source_types: List[str] = PydanticField(default_factory=list, exclude=True)
    source_odata_ids: List[str] = PydanticField(default_factory=list, exclude=True)
    related_resource_odata_ids: List[str] = PydanticField(
        default_factory=list, exclude=True
    )
