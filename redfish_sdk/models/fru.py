"""
FRU (Field Replaceable Unit) models.

"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Status
from .oem import MainBoard


class FruChassis(BaseModel):
    """FRU chassis component info."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    chassis_part_number: Optional[str] = Field(None, alias="ChassisPartNumber")
    chassis_serial_number: Optional[str] = Field(None, alias="ChassisSerialNumber")
    chassis_type: Optional[str] = Field(None, alias="ChassisType")


class FruProduct(BaseModel):
    """FRU product info."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    name: Optional[str] = Field(None, alias="Name")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    version: Optional[str] = Field(None, alias="Version")
    asset_tag: Optional[str] = Field(None, alias="AssetTag")


class FruDevice(BaseModel):
    """FRU device info (card, module, etc.)."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: Optional[str] = Field(None, alias="Name")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")


class Fru(Entity):
    """
    FRU (Field Replaceable Unit) information resource.
    Contains hardware inventory info like board, chassis, and product details.

    Retrieved via the OEM FRU link in the System or Chassis resource:
    - system.oem.bmc.fru.odata_id

    """
    chassis: Optional[FruChassis] = Field(None, alias="Chassis")
    board: Optional[MainBoard] = Field(None, alias="MainBoard")
    product: Optional[FruProduct] = Field(None, alias="Product")
    device: Optional[FruDevice] = Field(None, alias="device")
    status: Optional[Status] = Field(None, alias="Status")
