"""Typed Redfish action descriptors and ActionInfo metadata."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import Entity


class ActionDescriptor(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    target: Optional[str] = Field(None, alias="target")
    title: Optional[str] = Field(None, alias="title")
    action_info: Optional[str] = Field(None, alias="@Redfish.ActionInfo")

    @field_validator("target", "action_info", mode="before")
    @classmethod
    def valid_uri(cls, value: Any) -> Optional[str]:
        return value if isinstance(value, str) else None


class ActionMap(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def __getitem__(self, name: str) -> Any:
        """Preserve legacy subscript access while exposing typed fields."""
        return self.model_dump(by_alias=True, exclude_none=True)[name]

    def get(self, name: str, default: Any = None) -> Any:
        """Retain dictionary-style reads for existing OEM consumers."""
        return self.model_dump(by_alias=True, exclude_none=True).get(name, default)


class ActionInfoParameter(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: Optional[str] = Field(None, alias="Name")
    required: Optional[bool] = Field(None, alias="Required")
    data_type: Optional[str] = Field(None, alias="DataType")
    object_data_type: Optional[str] = Field(None, alias="ObjectDataType")
    allowable_values: Optional[List[Any]] = Field(None, alias="AllowableValues")
    minimum_value: Optional[float] = Field(None, alias="MinimumValue")
    maximum_value: Optional[float] = Field(None, alias="MaximumValue")


class ActionInfo(Entity):
    parameters: Optional[List[ActionInfoParameter]] = Field(None, alias="Parameters")

    def allowable_values(self, parameter_name: str) -> Optional[List[Any]]:
        parameter = self.parameter(parameter_name)
        return parameter.allowable_values if parameter else None

    def parameter(self, parameter_name: str) -> Optional[ActionInfoParameter]:
        for parameter in self.parameters or []:
            if parameter.name == parameter_name:
                return parameter
        return None
