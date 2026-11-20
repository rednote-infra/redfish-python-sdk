"""
FRU (Field Replaceable Unit) models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .common import Entity, Link, Status
from .oem import MainBoard


class FruChassis(BaseModel):
    """FRU chassis component info."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    chassis_part_number: Optional[str] = Field(None, validation_alias=AliasChoices("ChassisPartNumber", "PartNumber"))
    chassis_serial_number: Optional[str] = Field(None, validation_alias=AliasChoices("ChassisSerialNumber", "SerialNumber"))
    chassis_type: Optional[str] = Field(None, alias="ChassisType")


class FruProduct(BaseModel):
    """FRU product info."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    # Enginetech BMCs expose no standard Redfish "Name" / "PrettyName" in the
    # Product node; the real product name lives in the OEM "ProductName" key.
    # This alias is required to match the Enginetech layout.
    name: Optional[str] = Field(None, validation_alias=AliasChoices("Name", "PrettyName", "ProductName"))
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


class XFusionFruCollection(BaseModel):
    """Collection of xFusion (iBMC family) FRU devices, e.g. ``Chassis/<id>/Fru``."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    members: Optional[List[Link]] = Field(None, alias="Members")


class XFusionFru(Entity):
    """One xFusion FRU device record (``#Fru.v1_0_0.Fru``)."""
    chassis_type: Optional[str] = Field(None, alias="ChassisType")
    chassis_part_number: Optional[str] = Field(None, alias="ChassisPartNumber")
    chassis_serial: Optional[str] = Field(None, alias="ChassisSerial")
    board_mfg_date: Optional[str] = Field(None, alias="BoardMfgDate")
    board_mfg: Optional[str] = Field(None, alias="BoardMfg")
    board_product: Optional[str] = Field(None, alias="BoardProduct")
    board_serial: Optional[str] = Field(None, alias="BoardSerial")
    board_part_number: Optional[str] = Field(None, alias="BoardPartNumber")
    product_manufacturer: Optional[str] = Field(None, alias="ProductManufacturer")
    product_name: Optional[str] = Field(None, alias="ProductName")
    product_part_number: Optional[str] = Field(None, alias="ProductPartNumber")
    product_version: Optional[str] = Field(None, alias="ProductVersion")
    product_serial: Optional[str] = Field(None, alias="ProductSerial")
    product_asset_tag: Optional[str] = Field(None, alias="ProductAssetTag")

    def to_fru(self) -> Fru:
        """Map this flat record onto the standard :class:`Fru` layout."""
        return Fru.model_validate(
            {
                "@odata.id": self.odata_id,
                "MainBoard": self.model_dump(by_alias=True, exclude_none=True),
                "Product": {
                    "Manufacturer": self.product_manufacturer,
                    "Name": self.product_name,
                    "PartNumber": self.product_part_number,
                    "SerialNumber": self.product_serial,
                    "Version": self.product_version,
                    "AssetTag": self.product_asset_tag,
                },
                "Chassis": {
                    "ChassisPartNumber": self.chassis_part_number,
                    "ChassisSerialNumber": self.chassis_serial,
                },
            }
        )
