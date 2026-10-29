"""PolicyService and Policy resource models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link, Status


class PolicyModel(BaseModel):
    """Base model that preserves future standard and OEM policy fields."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class PolicyEventResponse(PolicyModel):
    message_args: Optional[List[str]] = Field(None, alias="MessageArgs")
    message_id: Optional[str] = Field(None, alias="MessageId")
    message_origin_of_condition: Optional[str] = Field(
        None, alias="MessageOriginOfCondition"
    )


class PolicyHTTPResponse(PolicyModel):
    body: Optional[str] = Field(None, alias="Body")
    headers: Optional[Dict[str, str]] = Field(None, alias="Headers")
    operation: Optional[str] = Field(None, alias="Operation")


class PolicyCondition(PolicyModel):
    compare_value: Optional[str] = Field(None, alias="CompareValue")
    operator: Optional[str] = Field(None, alias="Operator")
    property_path: Optional[str] = Field(None, alias="PropertyPath")
    resource_path: Optional[str] = Field(None, alias="ResourcePath")
    subordinate_conditions: Optional[List[PolicyCondition]] = Field(
        None, alias="SubordinateConditions"
    )
    type: Optional[str] = Field(None, alias="Type")


class PolicyResponse(PolicyModel):
    delay_seconds: Optional[int] = Field(None, alias="DelaySeconds", ge=0)
    event: Optional[PolicyEventResponse] = Field(None, alias="Event")
    http: Optional[PolicyHTTPResponse] = Field(None, alias="HTTP")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")
    reset_type: Optional[str] = Field(None, alias="ResetType")
    response_action: Optional[str] = Field(None, alias="ResponseAction")
    target_uri: Optional[str] = Field(None, alias="TargetURI")


class Policy(Entity):
    enabled: Optional[bool] = Field(None, alias="Enabled")
    predefined: Optional[bool] = Field(None, alias="Predefined")
    response: Optional[List[PolicyResponse]] = Field(None, alias="Response")
    trigger_condition: Optional[PolicyCondition] = Field(
        None, alias="TriggerCondition"
    )
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")
    links: Optional[Dict[str, Any]] = Field(None, alias="Links")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class PolicyService(Entity):
    resource_types_supported: Optional[List[str]] = Field(
        None, alias="ResourceTypesSupported"
    )
    condition_types_supported: Optional[List[str]] = Field(
        None, alias="ConditionTypesSupported"
    )
    actions_supported: Optional[List[str]] = Field(None, alias="ActionsSupported")
    operating_mode: Optional[str] = Field(None, alias="OperatingMode")
    policies: Optional[Link] = Field(None, alias="Policies")
    status: Optional[Status] = Field(None, alias="Status")
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")
    links: Optional[Dict[str, Any]] = Field(None, alias="Links")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class PolicyCreate(PolicyModel):
    id: str = Field(alias="Id")
    name: str = Field(alias="Name")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    response: List[PolicyResponse] = Field(alias="Response")
    trigger_condition: PolicyCondition = Field(alias="TriggerCondition")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class PolicyPatch(Entity):
    """Writable Policy fields with an ETag excluded from the JSON body."""

    odata_etag: Optional[str] = Field(None, alias="@odata.etag", exclude=True)
    enabled: Optional[bool] = Field(None, alias="Enabled")
    response: Optional[List[PolicyResponse]] = Field(None, alias="Response")
    trigger_condition: Optional[PolicyCondition] = Field(
        None, alias="TriggerCondition"
    )
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")
