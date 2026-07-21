"""
GPU (Graphics Processing Unit) component models.

"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity


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
