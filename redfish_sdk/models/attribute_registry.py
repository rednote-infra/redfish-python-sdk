"""Attribute Registry documents, separate from message-registry documents."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from ..exceptions import RedfishValidationError, RegistryResolutionError
from .common import Entity

ATTRIBUTE_REGISTRY_TYPE = "AttributeRegistry"
ScalarValue = Optional[Union[StrictStr, StrictBool, StrictInt, StrictFloat]]


class AttributeType(str, Enum):
    ENUMERATION = "Enumeration"
    STRING = "String"
    INTEGER = "Integer"
    BOOLEAN = "Boolean"
    PASSWORD = "Password"


class AttributeValue(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    value_name: str = Field(alias="ValueName")
    value_display_name: Optional[str] = Field(None, alias="ValueDisplayName")


class AttributeDefinition(BaseModel):
    """Static metadata; unknown fields/types remain available for future schemas."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    attribute_name: str = Field(alias="AttributeName")
    type: Optional[Union[AttributeType, str]] = Field(None, alias="Type")
    display_name: Optional[str] = Field(None, alias="DisplayName")
    display_order: Optional[int] = Field(None, alias="DisplayOrder")
    help_text: Optional[str] = Field(None, alias="HelpText")
    warning_text: Optional[str] = Field(None, alias="WarningText")
    menu_path: Optional[str] = Field(None, alias="MenuPath")
    default_value: ScalarValue = Field(None, alias="DefaultValue", repr=False)
    current_value: ScalarValue = Field(None, alias="CurrentValue", repr=False)
    lower_bound: Optional[int] = Field(None, alias="LowerBound")
    upper_bound: Optional[int] = Field(None, alias="UpperBound")
    scalar_increment: Optional[int] = Field(None, alias="ScalarIncrement")
    min_length: Optional[int] = Field(None, alias="MinLength")
    max_length: Optional[int] = Field(None, alias="MaxLength")
    read_only: Optional[bool] = Field(None, alias="ReadOnly")
    immutable: Optional[bool] = Field(None, alias="Immutable")
    write_only: Optional[bool] = Field(None, alias="WriteOnly")
    reset_required: Optional[bool] = Field(None, alias="ResetRequired")
    hidden: Optional[bool] = Field(None, alias="Hidden")
    gray_out: Optional[bool] = Field(None, alias="GrayOut")
    values: Optional[List[AttributeValue]] = Field(None, alias="Value")
    value_expression: Optional[str] = Field(None, alias="ValueExpression")

    def validate_value(self, value: Any) -> None:
        """Check static type/bounds/values without coercion or value disclosure.

        This is not a dependency evaluator: runtime conditional constraints and
        ValueExpression semantics must still be checked by the BMC/caller.
        """
        reason = None
        if self.read_only or self.immutable:
            reason = "is read-only or immutable"
        elif self.type == AttributeType.BOOLEAN:
            if type(value) is not bool:
                reason = "requires a boolean"
        elif self.type == AttributeType.INTEGER:
            if type(value) is not int:
                reason = "requires an integer"
            elif ((self.lower_bound is not None and value < self.lower_bound)
                  or (self.upper_bound is not None and value > self.upper_bound)):
                reason = "is outside its advertised bounds"
        elif self.type in (AttributeType.STRING, AttributeType.PASSWORD, AttributeType.ENUMERATION):
            if not isinstance(value, str):
                reason = "requires a string"
            elif self.type == AttributeType.ENUMERATION and (
                not self.values or value not in [item.value_name for item in self.values]
            ):
                reason = "is not an advertised enumeration value"
            elif ((self.min_length is not None and len(value) < self.min_length)
                  or (self.max_length is not None and len(value) > self.max_length)):
                reason = "does not satisfy its advertised string length"
        else:
            reason = "has no supported type for local validation"
        if reason:
            raise RedfishValidationError(f"Attribute {self.attribute_name!r} {reason}")


class AttributeMenu(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    menu_name: Optional[str] = Field(None, alias="MenuName")
    menu_path: Optional[str] = Field(None, alias="MenuPath")
    display_name: Optional[str] = Field(None, alias="DisplayName")
    display_order: Optional[int] = Field(None, alias="DisplayOrder")
    read_only: Optional[bool] = Field(None, alias="ReadOnly")
    hidden: Optional[bool] = Field(None, alias="Hidden")
    gray_out: Optional[bool] = Field(None, alias="GrayOut")


class AttributeMapFrom(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    map_from_attribute: Optional[str] = Field(None, alias="MapFromAttribute")
    map_from_property: Optional[str] = Field(None, alias="MapFromProperty")
    map_from_condition: Optional[str] = Field(None, alias="MapFromCondition")
    map_from_value: ScalarValue = Field(None, alias="MapFromValue")
    map_terms: Optional[str] = Field(None, alias="MapTerms")
    subexpressions: Optional[List[AttributeMapFrom]] = Field(None, alias="Subexpressions")


class AttributeDependencyMap(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    map_from: List[AttributeMapFrom] = Field(default_factory=list, alias="MapFrom")
    map_to_attribute: Optional[str] = Field(None, alias="MapToAttribute")
    map_to_property: Optional[str] = Field(None, alias="MapToProperty")
    map_to_value: ScalarValue = Field(None, alias="MapToValue")


class AttributeDependency(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    dependency_for: Optional[str] = Field(None, alias="DependencyFor")
    type: Optional[str] = Field(None, alias="Type")
    dependency: Optional[AttributeDependencyMap] = Field(None, alias="Dependency")


class AttributeRegistryEntries(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    attributes: List[AttributeDefinition] = Field(default_factory=list, alias="Attributes")
    menus: List[AttributeMenu] = Field(default_factory=list, alias="Menus")
    dependencies: List[AttributeDependency] = Field(default_factory=list, alias="Dependencies")


class AttributeRegistry(Entity):
    """An AttributeRegistry document, not its advertised RegistryFile wrapper."""
    language: Optional[str] = Field(None, alias="Language")
    registry_version: Optional[str] = Field(None, alias="RegistryVersion")
    owning_entity: Optional[str] = Field(None, alias="OwningEntity")
    registry_entries: Optional[AttributeRegistryEntries] = Field(None, alias="RegistryEntries")

    @model_validator(mode="before")
    @classmethod
    def _require_attribute_document(cls, value):
        if isinstance(value, dict):
            kind = str(value.get("@odata.type") or "")
            if (kind and not kind.startswith(f"#{ATTRIBUTE_REGISTRY_TYPE}.")) or "Messages" in value:
                raise ValueError("Expected an AttributeRegistry document")
            if not kind and "RegistryEntries" not in value:
                raise ValueError("AttributeRegistry requires a type discriminator or RegistryEntries")
        return value

    def get_attribute(self, name: str) -> AttributeDefinition:
        if self.registry_entries is None:
            raise RegistryResolutionError("Attribute registry has no RegistryEntries metadata")
        matches = [item for item in self.registry_entries.attributes if item.attribute_name == name]
        if len(matches) != 1:
            raise RegistryResolutionError(f"Attribute {name!r} is missing or ambiguous in the registry")
        return matches[0]

    def validate_attribute_values(self, values: Dict[str, Any]) -> None:
        """Validate static values only; dependencies/expressions remain unevaluated.

        Passing this check does not guarantee that the BMC accepts the update.
        Inspect registry_entries.dependencies for runtime conditional constraints.
        ScalarIncrement is a user-interface stepping hint (zero allows free-form
        input), not an absolute stateless value constraint.
        """
        if not isinstance(values, dict):
            raise RedfishValidationError("Attribute values must be a dictionary")
        for name, value in values.items():
            self.get_attribute(name).validate_value(value)
