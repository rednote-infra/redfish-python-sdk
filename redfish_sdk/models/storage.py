"""
Storage component models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status


class CacheSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    persistent_cache_size_mib: Optional[int] = Field(None, alias="PersistentCacheSizeMiB")
    total_cache_size_mib: Optional[int] = Field(None, alias="TotalCacheSizeMiB")
    status: Optional[Status] = Field(None, alias="Status")


class Identifier(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    durable_name: Optional[str] = Field(None, alias="DurableName")
    durable_name_format: Optional[str] = Field(None, alias="DurableNameFormat")


class StorageController(BaseModel):
    """Embedded storage controller info within a Storage resource."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    odata_id: Optional[str] = Field(None, alias="@odata.id")
    cache_summary: Optional[CacheSummary] = Field(None, alias="CacheSummary")
    firmware_version: Optional[str] = Field(None, alias="FirmwareVersion")
    identifiers: Optional[List[Identifier]] = Field(None, alias="Identifiers")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    member_id: Optional[str] = Field(None, alias="MemberId")
    model: Optional[str] = Field(None, alias="Model")
    name: Optional[str] = Field(None, alias="Name")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    speed_gbps: Optional[int] = Field(None, alias="SpeedGbps")
    status: Optional[Status] = Field(None, alias="Status")
    supported_controller_protocols: Optional[List[str]] = Field(
        None, alias="SupportedControllerProtocols"
    )
    supported_device_protocols: Optional[List[str]] = Field(
        None, alias="SupportedDeviceProtocols"
    )


class Storage(Entity):
    """
    Represents a storage controller.
    Endpoint: /redfish/v1/Systems/{systemId}/Storage/{storageId}

    """
    drives: Optional[List[Link]] = Field(None, alias="Drives", validate="list")
    storage_controllers: Optional[List[StorageController]] = Field(
        None, alias="StorageControllers", validate="list"
    )
    volumes: Optional[Link] = Field(None, alias="Volumes")
    status: Optional[Status] = Field(None, alias="Status", validate="status")


class Volume(Entity):
    """
    Represents a storage volume.
    Endpoint: /redfish/v1/Systems/{systemId}/Storage/{storageId}/Volumes/{volumeId}
    """
    volume_type: Optional[str] = Field(None, alias="VolumeType")
    capacity_bytes: Optional[int] = Field(None, alias="CapacityBytes")
    status: Optional[Status] = Field(None, alias="Status")
    raid_type: Optional[str] = Field(None, alias="RAIDType")
    optimum_io_size_bytes: Optional[int] = Field(None, alias="OptimumIOSizeBytes")
