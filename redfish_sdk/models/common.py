"""
Common base models for Redfish resources.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator

from ..exceptions import RedfishMissingAttributeError


def _has_value(value: Any) -> bool:
    """Return whether a required response value is usable."""
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _resource_uri(value: Any, info: ValidationInfo) -> str:
    """Resolve the best URI available for a response validation error."""
    context = info.context or {}
    if context.get("resource_uri"):
        return str(context["resource_uri"])
    if isinstance(value, dict) and _has_value(value.get("@odata.id")):
        return str(value["@odata.id"])
    return str(getattr(value, "odata_id", "") or "")


class ExtendedInfo(BaseModel):
    """Extended Redfish message information."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    message_id: Optional[str] = Field(None, alias="MessageId")
    message: Optional[str] = Field(None, alias="Message")
    message_args: Optional[List[str]] = Field(None, alias="MessageArgs")
    message_severity: Optional[str] = Field(None, alias="MessageSeverity")
    severity: Optional[str] = Field(None, alias="Severity")
    resolution: Optional[str] = Field(None, alias="Resolution")
    vendor_code: Optional[str] = Field(None, alias="VendorCode")
    related_properties: Optional[List[str]] = Field(None, alias="RelatedProperties")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class Condition(BaseModel):
    """A Redfish resource condition, including optional 2026.2 metadata."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    message_id: Optional[str] = Field(None, alias="MessageId")
    message: Optional[str] = Field(None, alias="Message")
    message_args: Optional[List[str]] = Field(None, alias="MessageArgs")
    message_severity: Optional[str] = Field(None, alias="MessageSeverity")
    severity: Optional[str] = Field(None, alias="Severity")
    resolution: Optional[str] = Field(None, alias="Resolution")
    vendor_code: Optional[str] = Field(None, alias="VendorCode")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class Link(BaseModel):
    """
    Base class for all Redfish resource links.
    Contains only the @odata.id field, which uniquely identifies the resource URL.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    odata_id: Optional[str] = Field(None, alias="@odata.id")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(odata_id={self.odata_id!r})"


class ApplyTime(str, Enum):
    """Standard apply times for pending settings (not create/delete actions)."""
    IMMEDIATE = "Immediate"
    ON_RESET = "OnReset"
    AT_MAINTENANCE_WINDOW_START = "AtMaintenanceWindowStart"
    IN_MAINTENANCE_WINDOW_ON_RESET = "InMaintenanceWindowOnReset"


class OperationApplyTime(str, Enum):
    """Standard apply times for create, delete, and action operations."""
    IMMEDIATE = "Immediate"
    ON_RESET = "OnReset"
    AT_MAINTENANCE_WINDOW_START = "AtMaintenanceWindowStart"
    IN_MAINTENANCE_WINDOW_ON_RESET = "InMaintenanceWindowOnReset"
    ON_START_UPDATE_REQUEST = "OnStartUpdateRequest"
    ON_TARGET_RESET = "OnTargetReset"


class MaintenanceWindow(BaseModel):
    """Standard maintenance-window assignment; timestamps retain wire format."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    maintenance_window_start_time: str = Field(alias="MaintenanceWindowStartTime")
    maintenance_window_duration_in_seconds: int = Field(alias="MaintenanceWindowDurationInSeconds", ge=0, strict=True)


class SettingsApplyTime(BaseModel):
    """Preferred settings schedule; unknown response enums remain readable."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    apply_time: Optional[Union[ApplyTime, str]] = Field(None, alias="ApplyTime")
    apply_time_allowable_values: Optional[List[str]] = Field(None, alias="ApplyTime@Redfish.AllowableValues")
    maintenance_window_start_time: Optional[str] = Field(None, alias="MaintenanceWindowStartTime")
    maintenance_window_duration_in_seconds: Optional[int] = Field(
        None, alias="MaintenanceWindowDurationInSeconds", ge=0, strict=True,
    )


class OperationApplyTimeSupport(BaseModel):
    """Advertised operation scheduling capability and governing window link."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    supported_values: Optional[List[str]] = Field(None, alias="SupportedValues")
    maintenance_window_resource: Optional[Link] = Field(None, alias="MaintenanceWindowResource")
    maintenance_window_start_time: Optional[str] = Field(None, alias="MaintenanceWindowStartTime")
    maintenance_window_duration_in_seconds: Optional[int] = Field(
        None, alias="MaintenanceWindowDurationInSeconds", ge=0, strict=True,
    )


class Settings(BaseModel):
    """Pending-resource discovery and results of the last settings application.

    ETag describes the active resource after settings were last applied, not
    the current concurrency validator of SettingsObject. Fetch that object.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    settings_object: Optional[Link] = Field(None, alias="SettingsObject")
    etag: Optional[str] = Field(None, alias="ETag")
    supported_apply_times: Optional[List[str]] = Field(None, alias="SupportedApplyTimes")
    maintenance_window_resource: Optional[Link] = Field(None, alias="MaintenanceWindowResource")
    time: Optional[str] = Field(None, alias="Time")
    messages: Optional[List[ExtendedInfo]] = Field(None, alias="Messages")


class Entity(Link):
    """
    Entity is the base class for all Redfish resources.
    Inherits from Link and adds common fields like Id, Name, Description, and ETag.

    """
    odata_context: Optional[str] = Field(None, alias="@odata.context")
    odata_type: Optional[str] = Field(None, alias="@odata.type")
    odata_etag: Optional[str] = Field(None, alias="@odata.etag")
    id: Optional[Union[str, int]] = Field(None, alias="Id")
    name: Optional[str] = Field(None, alias="Name")
    description: Optional[str] = Field(None, alias="Description")
    redfish_alias: Optional[str] = Field(None, alias="@Redfish.Alias")
    extended_info: Optional[List[ExtendedInfo]] = Field(
        None, alias="@Message.ExtendedInfo"
    )
    settings: Optional[Settings] = Field(None, alias="@Redfish.Settings")
    settings_apply_time: Optional[SettingsApplyTime] = Field(None, alias="@Redfish.SettingsApplyTime")
    operation_apply_time: Optional[Union[OperationApplyTime, str]] = Field(None, alias="@Redfish.OperationApplyTime")
    operation_apply_time_support: Optional[OperationApplyTimeSupport] = Field(
        None, alias="@Redfish.OperationApplyTimeSupport",
    )
    maintenance_window: Optional[MaintenanceWindow] = Field(None, alias="@Redfish.MaintenanceWindow")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r}, name={self.name!r})"


class IdentifiedEntity(Entity):
    """A top-level resource that requires a usable response identity."""

    @model_validator(mode="after")
    def _require_identity(self, info: ValidationInfo) -> IdentifiedEntity:
        if not self._has_usable_identity(info):
            raise RedfishMissingAttributeError(
                self._identity_attribute(),
                type(self).__name__,
                _resource_uri(self, info),
            )
        return self

    def _has_usable_identity(self, info: ValidationInfo) -> bool:
        return _has_value(self.odata_id) or _has_value(self.id)

    def _identity_attribute(self) -> str:
        return "@odata.id or Id"


T = TypeVar("T", bound=Link)


class Collection(Entity, Generic[T]):
    """
    Generic Redfish collection container.

    Example:
        /redfish/v1/Systems -> Collection[System]
        /redfish/v1/Chassis -> Collection[Chassis]

    """
    members_count: Optional[int] = Field(None, alias="Members@odata.count")
    members_next_link: Optional[str] = Field(None, alias="Members@odata.nextLink")
    members: Optional[List[T]] = Field(default_factory=list, alias="Members")

    @model_validator(mode="before")
    @classmethod
    def _require_member_links(cls, value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, dict) or value.get("Members") is None:
            raise RedfishMissingAttributeError(
                "Members", cls.__name__, _resource_uri(value, info)
            )
        for index, member in enumerate(value["Members"]):
            odata_id = (
                member.get("@odata.id")
                if isinstance(member, dict)
                else getattr(member, "odata_id", None)
            )
            if not _has_value(odata_id):
                raise RedfishMissingAttributeError(
                    f"Members[{index}].@odata.id",
                    cls.__name__,
                    _resource_uri(value, info),
                )
        return value


class Status(BaseModel):
    """
    Standard Redfish status object, used across most resource types.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    state: Optional[str] = Field(None, alias="State")
    health: Optional[str] = Field(None, alias="Health")
    health_rollup: Optional[str] = Field(None, alias="HealthRollup")


class RedfishErrorInfo(ExtendedInfo):
    """An error message whose malformed optional fields cannot hide its ID."""

    @field_validator("message", "message_args", "related_properties", mode="wrap")
    @classmethod
    def _optional_message_detail(cls, value, handler):
        try:
            return handler(value)
        except ValidationError:
            return None


class RedfishError(BaseModel):
    """
    Standard Redfish error response body.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    code: Optional[str] = Field(None, alias="code")
    message: Optional[str] = Field(None, alias="message")
    extended_info: Optional[List[ExtendedInfo]] = Field(None, alias="@Message.ExtendedInfo")


class RedfishErrorDetails(RedfishError):
    """HTTP error details with tolerant parsing of optional message fields."""

    extended_info: Optional[List[RedfishErrorInfo]] = Field(None, alias="@Message.ExtendedInfo")


class RedfishErrorResponse(BaseModel):
    """HTTP error envelope, also used for restricted successful session login."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    error: Optional[RedfishErrorDetails] = Field(None, alias="error")
    extended_info: Optional[List[RedfishErrorInfo]] = Field(None, alias="@Message.ExtendedInfo")


class RedfishResponse(BaseModel):
    """
    Generic Redfish operation response.
    Used for reset, patch and other mutation operations that return minimal data.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    error: Optional[RedfishError] = Field(None, alias="error")
    odata_id: Optional[str] = Field(None, alias="@odata.id")
    odata_type: Optional[str] = Field(None, alias="@odata.type")
    message: Optional[str] = Field(None, alias="Message")
    task_id: Optional[str] = Field(None, alias="TaskId")
    task_state: Optional[str] = Field(None, alias="TaskState")
    task_monitor: Optional[str] = Field(None, alias="TaskMonitor")
    http_status: Optional[int] = Field(None, alias="HttpStatus")
    task_uri: Optional[str] = Field(None, alias="TaskUri")
    retry_after: Optional[str] = Field(None, alias="RetryAfter")
