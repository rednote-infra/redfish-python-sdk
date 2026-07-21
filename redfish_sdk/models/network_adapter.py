"""
Network Adapter (NIC) component models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status
from .oem import Oem


class DataCenterBridging(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    capable: Optional[bool] = Field(None, alias="Capable")


class NPAR(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    npar_capable: Optional[bool] = Field(None, alias="NparCapable")
    npar_enabled: Optional[bool] = Field(None, alias="NparEnabled")


class VirtualFunction(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    device_max_count: Optional[int] = Field(None, alias="DeviceMaxCount")
    min_assignment_group_size: Optional[int] = Field(None, alias="MinAssignmentGroupSize")
    network_port_max_count: Optional[int] = Field(None, alias="NetworkPortMaxCount")


class VirtualizationOffload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    virtual_function: Optional[VirtualFunction] = Field(None, alias="VirtualFunction")


class ControllerCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    data_center_bridging: Optional[DataCenterBridging] = Field(None, alias="DataCenterBridging")
    npar: Optional[NPAR] = Field(None, alias="NPAR")
    network_device_function_count: Optional[int] = Field(
        None, alias="NetworkDeviceFunctionCount"
    )
    network_port_count: Optional[int] = Field(None, alias="NetworkPortCount")
    virtualization_offload: Optional[VirtualizationOffload] = Field(
        None, alias="VirtualizationOffload"
    )


class Controller(BaseModel):
    """Embedded NIC controller within a NetworkAdapter."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    controller_capabilities: Optional[ControllerCapabilities] = Field(
        None, alias="ControllerCapabilities"
    )
    firmware_package_version: Optional[str] = Field(None, alias="FirmwarePackageVersion")


class NetworkAdapter(Entity):
    """
    Represents a network adapter (NIC).
    Endpoint: /redfish/v1/Chassis/{chassisId}/NetworkAdapters/{networkAdapterId}

    """
    controllers: Optional[List[Controller]] = Field(None, alias="Controllers", validate="list")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="type=str")
    model: Optional[str] = Field(None, alias="Model", validate="type=str")
    network_device_functions: Optional[Link] = Field(None, alias="NetworkDeviceFunctions")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    ports: Optional[Link] = Field(None, alias="Ports")
    sku: Optional[str] = Field(None, alias="SKU")
    serial_number: Optional[str] = Field(None, alias="SerialNumber", validate="type=str")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    oem: Optional[Oem] = Field(None, alias="Oem")
