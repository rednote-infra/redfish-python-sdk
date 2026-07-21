"""
Common base models for Redfish resources.
"""
from __future__ import annotations

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class Link(BaseModel):
    """
    Base class for all Redfish resource links.
    Contains only the @odata.id field, which uniquely identifies the resource URL.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    odata_id: Optional[str] = Field(None, alias="@odata.id")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(odata_id={self.odata_id!r})"


class Entity(Link):
    """
    Entity is the base class for all Redfish resources.
    Inherits from Link and adds common fields like Id, Name, Description, and ETag.

    """
    odata_context: Optional[str] = Field(None, alias="@odata.context")
    odata_type: Optional[str] = Field(None, alias="@odata.type")
    odata_etag: Optional[str] = Field(None, alias="@odata.etag")
    id: Optional[str] = Field(None, alias="Id")
    name: Optional[str] = Field(None, alias="Name")
    description: Optional[str] = Field(None, alias="Description")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r}, name={self.name!r})"


T = TypeVar("T", bound=Link)


class Collection(Entity, Generic[T]):
    """
    Generic Redfish collection container.

    Example:
        /redfish/v1/Systems -> Collection[System]
        /redfish/v1/Chassis -> Collection[Chassis]

    """
    members_count: Optional[int] = Field(None, alias="Members@odata.count")
    members: Optional[List[T]] = Field(default_factory=list, alias="Members")


class Status(BaseModel):
    """
    Standard Redfish status object, used across most resource types.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    state: Optional[str] = Field(None, alias="State")
    health: Optional[str] = Field(None, alias="Health")
    health_rollup: Optional[str] = Field(None, alias="HealthRollup")


class ExtendedInfo(BaseModel):
    """Extended error information."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    message_id: Optional[str] = Field(None, alias="MessageId")
    message: Optional[str] = Field(None, alias="Message")
    message_args: Optional[List[str]] = Field(None, alias="MessageArgs")
    severity: Optional[str] = Field(None, alias="Severity")
    resolution: Optional[str] = Field(None, alias="Resolution")


class RedfishError(BaseModel):
    """
    Standard Redfish error response body.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    code: Optional[str] = Field(None, alias="code")
    message: Optional[str] = Field(None, alias="message")
    extended_info: Optional[List[ExtendedInfo]] = Field(None, alias="@Message.ExtendedInfo")


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
