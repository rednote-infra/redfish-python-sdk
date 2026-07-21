"""
Systems resource models.

"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status
from .gpu import Gpu, GpuOEM  # noqa: F401
from .memory import Memory, MemoryLocation  # noqa: F401
from .oem import Oem

# ---------------------------------------------------------------------------
# Re-export component models for backward compatibility
# ---------------------------------------------------------------------------
from .processor import Processor, ProcessorId  # noqa: F401
from .storage import (  # noqa: F401
    CacheSummary,
    Identifier,
    Storage,
    StorageController,
    Volume,
)

# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

class Boot(BaseModel):
    """
    Boot configuration for a system.
    Controls boot source override (e.g., PXE, HDD, CD-ROM).
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    boot_options: Optional[Link] = Field(None, alias="BootOptions")
    boot_source_override_enabled: Optional[str] = Field(None, alias="BootSourceOverrideEnabled")
    boot_source_override_mode: Optional[str] = Field(None, alias="BootSourceOverrideMode")
    boot_source_override_target: Optional[str] = Field(None, alias="BootSourceOverrideTarget")
    uefi_target_boot_source_override: Optional[str] = Field(None, alias="UefiTargetBootSourceOverride")
    allowable_values: Optional[List[str]] = Field(
        None, alias="BootSourceOverrideTarget@Redfish.AllowableValues"
    )


class BootSetting(BaseModel):
    """Request body for changing boot source via PATCH /redfish/v1/Systems/{id}."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    boot_source_override_enabled: Optional[str] = Field(None, alias="BootSourceOverrideEnabled")
    boot_source_override_mode: Optional[str] = Field(None, alias="BootSourceOverrideMode")
    boot_source_override_target: Optional[str] = Field(None, alias="BootSourceOverrideTarget")


class SystemPatchSetting(BaseModel):
    """PATCH request body for system-level settings (e.g., boot source)."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    boot: Optional[BootSetting] = Field(None, alias="Boot")


# ---------------------------------------------------------------------------
# BootOption
# ---------------------------------------------------------------------------

class BootOption(Entity):
    """
    A single boot option entry in the BootOptions collection.
    Endpoint: /redfish/v1/Systems/{id}/BootOptions/{optionId}

    Distinct from the legacy Boot/BootSourceOverrideTarget model: modern BMCs
    expose a per-option resource that can be enabled/disabled individually.
    """
    boot_option_reference: Optional[str] = Field(None, alias="BootOptionReference")
    boot_option_enabled: Optional[bool] = Field(None, alias="BootOptionEnabled")
    uefi_device_path: Optional[str] = Field(None, alias="UefiDevicePath")
    display_name: Optional[str] = Field(None, alias="DisplayName")
    alias: Optional[str] = Field(None, alias="Alias")


class BootOptionPatchSetting(BaseModel):
    """PATCH request body for toggling a single BootOption.BootOptionEnabled."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    boot_option_enabled: Optional[bool] = Field(None, alias="BootOptionEnabled")


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

class ResetAction(BaseModel):
    """Describes the Reset action target and allowable values."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    target: Optional[str] = Field(None, alias="target")
    reset_type_allowable_values: Optional[List[str]] = Field(
        None, alias="ResetType@Redfish.AllowableValues"
    )
    action_info: Optional[str] = Field(None, alias="@Redfish.ActionInfo")


class SystemActions(BaseModel):
    """Actions available on a system resource (e.g., Reset)."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    computer_system_reset: Optional[ResetAction] = Field(
        None, alias="#ComputerSystem.Reset"
    )
    reset_type_allowable_values: Optional[List[str]] = Field(
        None, alias="ResetType@Redfish.AllowableValues"
    )


# ---------------------------------------------------------------------------
# System Links
# ---------------------------------------------------------------------------

class SystemLinks(BaseModel):
    """Links section within a System resource."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    chassis: Optional[List[Link]] = Field(None, alias="Chassis")
    pcie_devices: Optional[List[Link]] = Field(None, alias="PCIeDevices")
    managed_by: Optional[List[Link]] = Field(None, alias="ManagedBy")


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

class System(Entity):
    """
    Represents a single computer system (physical server).
    Endpoint: /redfish/v1/Systems/{systemId}

    """
    actions: Optional[SystemActions] = Field(None, alias="Actions")
    asset_tag: Optional[str] = Field(None, alias="AssetTag")
    bios_version: Optional[str] = Field(None, alias="BiosVersion", validate="type=str")
    bios: Optional[Link] = Field(None, alias="Bios")
    host_name: Optional[str] = Field(None, alias="HostName")
    indicator_led: Optional[str] = Field(None, alias="IndicatorLED")
    last_reset_time: Optional[str] = Field(None, alias="LastResetTime")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    power_state: Optional[str] = Field(None, alias="PowerState", validate="required,oneof=On Off PoweringOn PoweringOff")
    sub_model: Optional[str] = Field(None, alias="SubModel")
    system_type: Optional[str] = Field(None, alias="SystemType", validate="type=str")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="required,type=str")
    model: Optional[str] = Field(None, alias="Model", validate="required,type=str")
    serial_number: Optional[str] = Field(None, alias="SerialNumber", validate="required,type=str")
    sku: Optional[str] = Field(None, alias="SKU")
    uuid: Optional[str] = Field(None, alias="UUID", validate="type=str")
    power_restore_policy: Optional[str] = Field(None, alias="PowerRestorePolicy")

    # Sub-resource links
    certificates: Optional[Link] = Field(None, alias="Certificates")
    ethernet_interfaces: Optional[Link] = Field(None, alias="EthernetInterfaces")
    graphics_controllers: Optional[Link] = Field(None, alias="GraphicsControllers")
    log_services: Optional[Link] = Field(None, alias="LogServices")
    memory: Optional[Link] = Field(None, alias="Memory")
    storage: Optional[Link] = Field(None, alias="Storage")
    processors: Optional[Link] = Field(None, alias="Processors")
    secure_boot: Optional[Link] = Field(None, alias="SecureBoot")
    simple_storage: Optional[Link] = Field(None, alias="SimpleStorage")
    usb_controllers: Optional[Link] = Field(None, alias="USBControllers")
    virtual_media: Optional[Link] = Field(None, alias="VirtualMedia")
    network_interfaces: Optional[Link] = Field(None, alias="NetworkInterfaces")

    # PCIe devices (array of links)
    pcie_devices: Optional[List[Link]] = Field(None, alias="PCIeDevices")
    pcie_devices_count: Optional[int] = Field(None, alias="PCIeDevices@odata.count")

    boot: Optional[Boot] = Field(None, alias="Boot")
    links: Optional[SystemLinks] = Field(None, alias="Links")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    oem: Optional[Oem] = Field(None, alias="Oem")


# ---------------------------------------------------------------------------
# BIOS
# ---------------------------------------------------------------------------

class Bios(Entity):
    """
    BIOS settings resource.
    Endpoint: /redfish/v1/Systems/{systemId}/Bios
    """
    bios_version: Optional[str] = Field(None, alias="BiosVersion")
    attributes: Optional[Any] = Field(None, alias="Attributes")
