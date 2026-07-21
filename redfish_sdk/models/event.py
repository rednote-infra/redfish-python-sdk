"""
Event service models.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from .common import Entity, Link, Status  # noqa: F401  (Status kept for downstream imports)


class EventService(Entity):
    """
    The Event service provides event subscription management.
    Endpoint: /redfish/v1/EventService
    """
    subscriptions: Optional[Link] = Field(None, alias="Subscriptions")
    delivery_retry_attempts: Optional[int] = Field(None, alias="DeliveryRetryAttempts")
    delivery_retry_interval_seconds: Optional[int] = Field(
        None, alias="DeliveryRetryIntervalSeconds"
    )
    event_types_for_subscription: Optional[List[str]] = Field(
        None, alias="EventTypesForSubscription"
    )
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    status: Optional[Status] = Field(None, alias="Status")
    # Redfish Actions block (e.g. #EventService.SubmitTestEvent).
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")


class Subscription(Entity):
    """
    Represents an event subscription (webhook).
    Endpoint: /redfish/v1/EventService/Subscriptions/{subscriptionId}
    """
    context: Optional[str] = Field(None, alias="Context")
    destination: Optional[str] = Field(None, alias="Destination")
    event_types: Optional[List[str]] = Field(None, alias="EventTypes")
    # Type widened to Any: different BMC vendors return either a dict
    # (``{"X-Auth-Token": "..."}``) or a list of dicts
    # (``[{"X-Auth-Token": "..."}]``). Mirrors the lenient style used by
    # ``EventService.actions`` above.
    http_headers: Optional[Any] = Field(None, alias="HttpHeaders")
    oem_type: Optional[str] = Field(None, alias="OemSubscriptionType")
    protocol: Optional[str] = Field(None, alias="Protocol")
    registry_prefixes: Optional[List[str]] = Field(None, alias="RegistryPrefixes")
    resource_types: Optional[List[str]] = Field(None, alias="ResourceTypes")
    # Type widened to Any: per Redfish spec ``Status`` is a complex object
    # (``{"State": "Enabled", "Health": "OK"}``), but multiple BMC vendors
    # return a bare string (e.g. ``"Enabled"``) for EventDestination.
    # Mirrors the lenient style of ``http_headers`` above.
    status: Optional[Any] = Field(None, alias="Status")
    subscription_type: Optional[str] = Field(None, alias="SubscriptionType")
    # —— Additional fields observed across BMC vendors ——
    origin_resources: Optional[List[Dict[str, Any]]] = Field(
        None, alias="OriginResources"
    )
    delivery_retry_policy: Optional[str] = Field(
        None, alias="DeliveryRetryPolicy"
    )
    message_ids: Optional[List[str]] = Field(None, alias="MessageIds")
    event_format_type: Optional[str] = Field(None, alias="EventFormatType")
    severities: Optional[List[str]] = Field(None, alias="Severities")
