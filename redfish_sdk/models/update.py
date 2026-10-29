"""
Update service models.

"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .common import Entity, Link, RedfishResponse, Status


class UpdateService(Entity):
    """
    The Update service provides firmware update capabilities.
    Endpoint: /redfish/v1/UpdateService
    """
    firmware_inventory: Optional[Link] = Field(None, alias="FirmwareInventory")
    software_inventory: Optional[Link] = Field(None, alias="SoftwareInventory")
    update_service_capabilities: Optional[Link] = Field(
        None, alias="UpdateServiceCapabilities"
    )
    local_image_store: Optional[Link] = Field(None, alias="LocalImageStore")
    client_certificates: Optional[Link] = Field(None, alias="ClientCertificates")
    http_push_uri: Optional[str] = Field(None, alias="HttpPushUri")
    multi_part_http_push_uri: Optional[str] = Field(
        None,
        alias="MultipartHttpPushUri",
        validation_alias=AliasChoices("MultipartHttpPushUri", "MultiPartHttpPushUri"),
    )
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    status: Optional[Status] = Field(None, alias="Status")
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")


class FirmwareUpdateResponse(RedfishResponse):
    """Firmware operation result, including HTTP task-monitor references."""

    task_id: Optional[str] = Field(None, alias="TaskId", validation_alias=AliasChoices("TaskId", "Id"))


class FirmwareInventory(Entity):
    """
    Represents a firmware component in the inventory.
    Endpoint: /redfish/v1/UpdateService/FirmwareInventory/{inventoryId}

    """
    description: Optional[str] = Field(None, alias="Description")
    lowest_supported_version: Optional[str] = Field(None, alias="LowestSupportedVersion")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    related_item: Optional[List[Link]] = Field(None, alias="RelatedItem")
    release_date: Optional[str] = Field(None, alias="ReleaseDate")
    software_id: Optional[str] = Field(None, alias="SoftwareId")
    status: Optional[Status] = Field(None, alias="Status")
    updateable: Optional[bool] = Field(None, alias="Updateable")
    version: Optional[str] = Field(None, alias="Version")


class UpdateServiceCapabilities(Entity):
    """Parameters advertised for standard UpdateService requests."""

    allowable_targets: Optional[List[str]] = Field(None, alias="AllowableTargets")
    allowable_staging: Optional[List[str]] = Field(None, alias="AllowableStaging")
    allowable_target_reference_types: Optional[List[str]] = Field(None, alias="AllowableTargetReferenceTypes")
    targets_parameter_supported: Optional[bool] = Field(None, alias="TargetsParameterSupported")
    exclude_targets_parameter_supported: Optional[bool] = Field(None, alias="ExcludeTargetsParameterSupported")
    force_update_parameter_supported: Optional[bool] = Field(None, alias="ForceUpdateParameterSupported")
    stage_parameter_supported: Optional[bool] = Field(None, alias="StageParameterSupported")
    local_image_parameter_supported: Optional[bool] = Field(None, alias="LocalImageParameterSupported")


class SoftwareInventoryLinks(BaseModel):
    """Targets associated with a software image lifecycle state."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    active_targets: Optional[List[Link]] = Field(None, alias="ActiveTargets")
    staged_targets: Optional[List[Link]] = Field(None, alias="StagedTargets")
    armed_targets: Optional[List[Link]] = Field(None, alias="ArmedTargets")


class SoftwareInventory(FirmwareInventory):
    """A software image and its active, staged, or armed lifecycle state."""

    active: Optional[bool] = Field(None, alias="Active")
    staged: Optional[bool] = Field(None, alias="Staged")
    armed: Optional[bool] = Field(None, alias="Armed")
    image_state: Optional[str] = Field(None, alias="ImageState")
    oem_image_state: Optional[str] = Field(None, alias="OEMImageState")
    image_data_uri: Optional[str] = Field(None, alias="ImageDataURI")
    release_type: Optional[str] = Field(None, alias="ReleaseType")
    reset_required_on_update: Optional[bool] = Field(None, alias="ResetRequiredOnUpdate")
    size_bytes: Optional[int] = Field(None, alias="SizeBytes")
    uefi_device_paths: Optional[List[str]] = Field(None, alias="UefiDevicePaths")
    version_scheme: Optional[str] = Field(None, alias="VersionScheme")
    write_protected: Optional[bool] = Field(None, alias="WriteProtected")
    links: Optional[SoftwareInventoryLinks] = Field(None, alias="Links")
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")


class UpdateParameters(BaseModel):
    """Typed parameters shared by standard SimpleUpdate and multipart pushes."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    targets: Optional[List[str]] = Field(None, alias="Targets")
    exclude_targets: Optional[List[str]] = Field(None, alias="ExcludeTargets")
    force_update: Optional[bool] = Field(None, alias="ForceUpdate")
    stage: Optional[bool] = Field(None, alias="Stage")
    local_image: Optional[bool] = Field(None, alias="LocalImage")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class ClientCertificate(Entity):
    """
    Represents a client certificate for firmware update authentication.
    Endpoint: /redfish/v1/UpdateService/ClientCertificates/{certId}
    """
    certificate_string: Optional[str] = Field(None, alias="CertificateString")
    certificate_type: Optional[str] = Field(None, alias="CertificateType")
    issuer: Optional[dict] = Field(None, alias="Issuer")
    subject: Optional[dict] = Field(None, alias="Subject")
    valid_not_after: Optional[str] = Field(None, alias="ValidNotAfter")
    valid_not_before: Optional[str] = Field(None, alias="ValidNotBefore")
