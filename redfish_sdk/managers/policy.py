"""Capability-driven PolicyService discovery and policy lifecycle operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..exceptions import RedfishNotFoundError, RedfishValidationError
from ..models.common import Entity
from ..models.policy import (
    Policy,
    PolicyCondition,
    PolicyCreate,
    PolicyPatch,
    PolicyResponse,
    PolicyService,
)
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient


class PolicyServiceManager:
    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def service(self) -> PolicyService:
        """Get PolicyService through its optional Service Root link."""
        link = self._client._get_root().policy_service
        if not link or not link.odata_id:
            raise RedfishNotFoundError(
                "Service Root does not advertise PolicyService"
            )
        return self._http.get(link.odata_id, PolicyService)

    def _policies_path(self, service: Optional[PolicyService] = None) -> str:
        link = (service or self.service()).policies
        if not link or not link.odata_id:
            raise RedfishNotFoundError(
                "PolicyService does not advertise a Policies collection"
            )
        return link.odata_id

    def policies(self) -> List[Policy]:
        return self._client._get_collection(self._policies_path(), Policy)

    def policy(self, identifier: str) -> Policy:
        return select_member(self.policies(), identifier)

    def _validate_condition(
        self, condition: PolicyCondition, service: PolicyService
    ) -> None:
        supported = service.condition_types_supported or []
        if not condition.type or condition.type not in supported:
            raise RedfishValidationError(
                f"Unsupported policy condition type {condition.type!r}; "
                f"advertised values: {supported}"
            )
        for subordinate in condition.subordinate_conditions or []:
            self._validate_condition(subordinate, service)

    def _validate_response(
        self, response: PolicyResponse, service: PolicyService
    ) -> None:
        supported_actions = service.actions_supported or []
        if (
            not response.response_action
            or response.response_action not in supported_actions
        ):
            raise RedfishValidationError(
                f"Unsupported policy response action {response.response_action!r}; "
                f"advertised values: {supported_actions}"
            )
        if response.response_action != "Reset":
            return
        if not response.target_uri:
            raise RedfishValidationError(
                "Reset policy responses require a TargetURI"
            )
        target = self._http.get(response.target_uri, Entity)
        resource_type = (target.odata_type or "").rsplit(".", 1)[-1]
        supported_resources = service.resource_types_supported or []
        if not resource_type or resource_type not in supported_resources:
            raise RedfishValidationError(
                f"Unsupported policy target resource type {resource_type or 'unknown'!r}; "
                f"advertised values: {supported_resources}"
            )

    def _validate_definition(
        self,
        condition: Optional[PolicyCondition],
        responses: Optional[List[PolicyResponse]],
        service: Optional[PolicyService] = None,
    ) -> None:
        if condition is None and responses is None:
            return
        capabilities = service or self.service()
        if condition is not None:
            self._validate_condition(condition, capabilities)
        for response in responses or []:
            self._validate_response(response, capabilities)

    def create(
        self,
        policy_id: str,
        name: str,
        trigger_condition: PolicyCondition,
        responses: List[PolicyResponse],
        *,
        enabled: Optional[bool] = None,
        oem: Optional[Dict[str, Any]] = None,
    ) -> Policy:
        if not policy_id or not name:
            raise RedfishValidationError("Policy Id and Name must be non-empty")
        if not responses:
            raise RedfishValidationError("Policy Response must not be empty")
        service = self.service()
        self._validate_definition(trigger_condition, responses, service)
        body = PolicyCreate(
            id=policy_id,
            name=name,
            enabled=enabled,
            trigger_condition=trigger_condition,
            response=responses,
            oem=oem,
        )
        return self._http.post(
            self._policies_path(service), Policy, body=body
        )

    def update(
        self,
        identifier: str,
        *,
        trigger_condition: Optional[PolicyCondition] = None,
        responses: Optional[List[PolicyResponse]] = None,
        enabled: Optional[bool] = None,
        oem: Optional[Dict[str, Any]] = None,
    ) -> Policy:
        if all(
            value is None
            for value in (trigger_condition, responses, enabled, oem)
        ):
            raise RedfishValidationError("Supply at least one policy field to update")
        current = self.policy(identifier)
        if not current.odata_id:
            raise RedfishNotFoundError("Policy does not advertise @odata.id")
        definition_change = any(
            value is not None for value in (trigger_condition, responses, oem)
        )
        if current.predefined is True and definition_change:
            raise RedfishValidationError(
                "Cannot modify the definition of a predefined policy"
            )
        self._validate_definition(trigger_condition, responses)
        body = PolicyPatch(
            trigger_condition=trigger_condition,
            response=responses,
            enabled=enabled,
            oem=oem,
            odata_etag=current.odata_etag,
        )
        return self._http.patch(current.odata_id, Policy, body)

    def enable(self, identifier: str) -> Policy:
        return self.update(identifier, enabled=True)

    def disable(self, identifier: str) -> Policy:
        return self.update(identifier, enabled=False)

    def delete(self, identifier: str) -> str:
        current = self.policy(identifier)
        if current.predefined is True:
            raise RedfishValidationError("Cannot delete a predefined policy")
        if not current.odata_id:
            raise RedfishNotFoundError("Policy does not advertise @odata.id")
        response = self._http._request(
            "DELETE",
            current.odata_id,
            headers={"If-Match": current.odata_etag or "*"},
        )
        self._http._raise_for_status(response, current.odata_id)
        return response.text
