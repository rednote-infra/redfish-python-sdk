"""
Event service manager — manages event subscriptions.

"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..exceptions import RedfishValidationError
from ..models.event import EventService, Subscription

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


class EventServiceManager:
    """
    Manages Redfish Event subscriptions.

    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _resolve_subscription_path(self, id_or_uri: str) -> str:
        """
        Accept either a bare subscription Id (e.g. ``"1"``) or a full
        ``@odata.id`` path (e.g. ``"/redfish/v1/EventService/Subscriptions/1"``)
        and return the absolute Redfish path to GET/DELETE against.

        The dual-form is needed because some callers (e.g. those iterating
        over the ``Members`` block of the Subscriptions collection) already
        hold the absolute path.
        """
        if not isinstance(id_or_uri, str) or not id_or_uri:
            raise RedfishValidationError(
                "subscription id_or_uri must be a non-empty string"
            )
        if id_or_uri.startswith("/redfish/"):
            return id_or_uri
        event_service = self._client._get_event_service()
        return f"{event_service.subscriptions.odata_id}/{id_or_uri}"

    # ------------------------------------------------------------------
    # EventService resource
    # ------------------------------------------------------------------

    def service(self) -> EventService:
        """
        Get the full :class:`EventService` resource (incl. the Actions block).

        Differs from :meth:`subscriptions` which only returns the list of
        active subscriptions. Use this when you need the SubmitTestEvent
        action target or the EventTypesForSubscription allowable values.
        """
        return self._client._get_event_service()

    # ------------------------------------------------------------------
    # Subscription CRUD
    # ------------------------------------------------------------------

    def subscriptions(self) -> List[Subscription]:
        """
        Get the list of event subscriptions (collection-expanded).

        Internally lists the ``Subscriptions`` collection and fetches each
        member by its ``@odata.id``; members that fail to fetch are skipped
        with a warning.
        """
        event_service = self._client._get_event_service()
        return self._client._get_collection(
            event_service.subscriptions.odata_id, Subscription
        )

    def get_subscription(self, id_or_uri: str) -> Subscription:
        """
        Get a single subscription by its Id or full ``@odata.id``.

        Args:
            id_or_uri: Either a bare subscription Id (e.g. ``"1"``) or the
                full ``@odata.id`` path
                (e.g. ``"/redfish/v1/EventService/Subscriptions/1"``).

        Returns:
            The :class:`Subscription` resource.
        """
        path = self._resolve_subscription_path(id_or_uri)
        return self._http.get(path, Subscription)

    def subscribe(
        self,
        destination: str,
        event_types: Optional[List[str]] = None,
        context: Optional[str] = None,
        *,
        protocol: str = "Redfish",
        http_headers: Optional[Any] = None,
        origin_resources: Optional[List[Dict[str, Any]]] = None,
        subscription_type: Optional[str] = None,
        registry_prefixes: Optional[List[str]] = None,
        resource_types: Optional[List[str]] = None,
        message_ids: Optional[List[str]] = None,
        delivery_retry_policy: Optional[str] = None,
        event_format_type: Optional[str] = None,
        severities: Optional[List[str]] = None,
        oem_subscription_type: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        raw_body: Optional[Dict[str, Any]] = None,
    ) -> Subscription:
        """
        Create a new event subscription (webhook).

        The signature is intentionally vendor-agnostic: every Redfish
        Subscription field observed in the wild is exposed as a
        keyword-only parameter, and ``extra`` / ``raw_body`` give a final
        escape hatch for OEM-specific payloads. The SDK does **not** apply
        any vendor-default values; callers may attempt multiple payload
        shapes in sequence if a BMC rejects the first one.

        Args:
            destination: URL to receive events (e.g. ``"https://my-server/events"``).
            event_types: Optional list of event types (e.g. ``["Alert"]``).
            context: Optional context string identifying the subscription.
            protocol: Wire protocol; defaults to ``"Redfish"``.
            http_headers: Optional headers to be sent on the callback POST.
                Pass a ``dict`` (``{"X-Auth-Token": "..."}``) or a
                ``list[dict]`` — both forms are common across BMC vendors.
            origin_resources: Optional list of ``{"@odata.id": "..."}``
                filtering the resources of interest.
            subscription_type: Optional ``SubscriptionType`` value
                (e.g. ``"RedfishEvent"``, ``"SSE"``).
            registry_prefixes: Optional message-registry filter list.
            resource_types: Optional list of resource-type filters.
            message_ids: Optional list of message Ids to filter on.
            delivery_retry_policy: Optional retry policy value.
            event_format_type: Optional event format type.
            severities: Optional severity filter list.
            oem_subscription_type: Optional vendor-specific subscription type.
            extra: Optional dict shallow-merged into the request body —
                useful for one-off OEM fields without bypassing field hints.
            raw_body: If provided, **replaces** the auto-generated body
                entirely. Use this when a BMC accepts only a non-standard
                payload shape.

        Returns:
            The created :class:`Subscription` resource (as echoed by the BMC).
        """
        event_service = self._client._get_event_service()

        if raw_body is not None:
            body: Dict[str, Any] = dict(raw_body)
        else:
            body = {"Destination": destination, "Protocol": protocol}
            if event_types is not None:
                body["EventTypes"] = event_types
            if context is not None:
                body["Context"] = context
            if http_headers is not None:
                body["HttpHeaders"] = http_headers
            if origin_resources is not None:
                body["OriginResources"] = origin_resources
            if subscription_type is not None:
                body["SubscriptionType"] = subscription_type
            if registry_prefixes is not None:
                body["RegistryPrefixes"] = registry_prefixes
            if resource_types is not None:
                body["ResourceTypes"] = resource_types
            if message_ids is not None:
                body["MessageIds"] = message_ids
            if delivery_retry_policy is not None:
                body["DeliveryRetryPolicy"] = delivery_retry_policy
            if event_format_type is not None:
                body["EventFormatType"] = event_format_type
            if severities is not None:
                body["Severities"] = severities
            if oem_subscription_type is not None:
                body["OemSubscriptionType"] = oem_subscription_type
            if extra:
                body.update(extra)

        return self._http.post(
            event_service.subscriptions.odata_id,
            Subscription,
            raw_body=body,
        )

    def delete(self, id_or_uri: str) -> str:
        """
        Delete an event subscription.

        Args:
            id_or_uri: Either a bare subscription Id (e.g. ``"1"``) or the
                full ``@odata.id`` path
                (e.g. ``"/redfish/v1/EventService/Subscriptions/1"``).

        Returns:
            Raw response body (typically empty on 204).
        """
        path = self._resolve_subscription_path(id_or_uri)
        return self._http.delete(path)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def submit_test_event(
        self,
        event_type: str,
        message: Optional[str] = None,
        message_id: Optional[str] = None,
        severity: Optional[str] = None,
        message_args: Optional[List[str]] = None,
    ) -> None:
        """
        Invoke ``#EventService.SubmitTestEvent`` on the BMC.

        Args:
            event_type: Event type, e.g. ``"Alert"`` / ``"StatusChange"``.
                Subject to ``EventType@Redfish.AllowableValues`` on the BMC.
            message: Optional event message string.
            message_id: Optional Redfish MessageId.
            severity: Optional severity (e.g. ``"OK"`` / ``"Warning"`` / ``"Critical"``).
            message_args: Optional message argument list.

        Raises:
            RedfishValidationError: If EventService does not expose
                SubmitTestEvent or ``event_type`` is not in the allowable list.
        """
        from ..models.common import RedfishResponse

        es = self.service()
        actions = es.actions or {}
        action = actions.get("#EventService.SubmitTestEvent")
        if not isinstance(action, dict) or not action.get("target"):
            raise RedfishValidationError(
                "EventService does not expose #EventService.SubmitTestEvent action"
            )
        target = action["target"]
        allowable = action.get("EventType@Redfish.AllowableValues")
        if allowable and event_type not in allowable:
            raise RedfishValidationError(
                f"Event type '{event_type}' not in allowable values {allowable}"
            )

        body: dict = {"EventType": event_type}
        if message is not None:
            body["Message"] = message
        if message_id is not None:
            body["MessageId"] = message_id
        if severity is not None:
            body["Severity"] = severity
        if message_args is not None:
            body["MessageArgs"] = message_args

        logger.info("POST SubmitTestEvent (%s) -> %s", event_type, target)
        self._http.post(target, RedfishResponse, raw_body=body)
