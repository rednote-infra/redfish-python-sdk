"""
Shared helpers for fetching log services and their entries.

Used by both :mod:`redfish_sdk.managers.systems` and
:mod:`redfish_sdk.managers.managers` so the two log services share the
same behaviour: missing-LogServices guard, dynamic LogService URL
discovery (no path concatenation), and log_id auto-selection.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from ..exceptions import (
    RedfishException,
    RedfishNotFoundError,
    RedfishValidationError,
)
from ..models.logs import Log, LogEntry

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


def require_log_services_link(
    parent_resource: object,
    parent_name: str,
) -> str:
    """
    Extract ``LogServices.@odata.id`` from a System/Manager resource, raising
    a clear error when the BMC did not advertise a LogServices link at all.

    The ``Optional[Link]`` typing on ``System.log_services`` / ``Manager.log_services``
    reflects the Redfish spec: ``LogServices`` is an optional sub-resource and
    some lightweight BMCs (or disabled audit roles) genuinely omit it. Without
    this guard, callers crash with a bare ``AttributeError: 'NoneType' object``
    that doesn't reveal which BMC capability is missing.

    Args:
        parent_resource: A System or Manager instance with a ``log_services`` attr.
        parent_name: Human label for the error message (e.g. ``"System 1"``).

    Returns:
        The ``@odata.id`` of the LogServices collection.

    Raises:
        RedfishException: 404 when the parent resource does not expose
            LogServices.
    """
    link = getattr(parent_resource, "log_services", None)
    odata_id = getattr(link, "odata_id", None) if link is not None else None
    if not odata_id:
        raise RedfishException(
            404,
            f"{parent_name} does not expose a LogServices collection "
            f"(BMC returned no `LogServices` link on the resource)",
        )
    return odata_id


def resolve_log_service(
    client: "RedfishClient",
    log_services_odata_id: str,
    log_id: Optional[str],
) -> Log:
    """
    Resolve a single :class:`Log` resource by ID or auto-select when only one.

    Both branches discover the real per-LogService ``@odata.id`` by listing
    the parent ``LogServices`` collection and matching by ``Log.id`` —
    never assume the URL is ``f"{log_services_odata_id}/{log_id}"``. Some
    vendors (e.g. Huawei iBMC OEM logs) publish a non-standard child path,
    so trusting the collection link is the only correct approach.

    Args:
        client: RedfishClient instance (used to fetch the LogServices collection).
        log_services_odata_id: ``@odata.id`` of the parent ``LogServices`` collection.
        log_id: Explicit log service ID, or None to auto-select the sole member.

    Raises:
        RedfishException: 404 when the collection is empty.
        RedfishValidationError: When ``log_id`` is None and multiple members exist.
        RedfishNotFoundError: When the requested ``log_id`` is not present.
    """
    services = client._get_collection(log_services_odata_id, Log)
    if not services:
        raise RedfishException(
            404, f"No log services found under {log_services_odata_id}"
        )

    if log_id is None:
        if len(services) > 1:
            ids = [s.id for s in services if s.id]
            raise RedfishValidationError(
                f"Multiple log services found, please specify log_id. "
                f"Available: {ids}"
            )
        return services[0]

    # Explicit log_id — look it up by ``Log.id`` in the collection rather
    # than rebuilding the URL by string concatenation.
    matches = [s for s in services if s.id == log_id]
    if not matches:
        available = [s.id for s in services if s.id]
        raise RedfishNotFoundError(
            f"{log_services_odata_id}/{log_id} "
            f"(no log service with id={log_id!r}; available={available})"
        )
    return matches[0]


def fetch_log_entries(client: "RedfishClient", log: Log) -> List[LogEntry]:
    """
    Fetch all LogEntry items under a Log resource.

    Strategy: always GET the Entries collection link from
    ``log.entries.odata_id`` (NOT a hard-coded ``/Entries`` suffix) and
    expand its members one by one via the shared ``_get_collection``
    helper.

    Returns an empty list when the LogService has no Entries link at all
    (some BMCs expose log services without entries, e.g. a disabled audit
    log).

    History — why we don't use ``?$expand=.($levels=1)``:
        An earlier prototype tried ``$expand`` first and fell back to per-entry
        GET only on 4xx errors or bare-link responses. Real-world testing
        against multiple BMCs showed that
        some servers **silently swallow** the query and return an empty
        ``Members`` collection with ``Members@odata.count: 0`` even when
        actual entries exist. There is no reliable wire-level signal that
        distinguishes "BMC genuinely has no entries" from "BMC broke
        expand"; both look like the same valid Redfish empty collection.
        Per-entry GET via ``_get_collection`` is the only behaviour that
        is correct across every BMC we have seen. Callers needing more
        throughput can parallelise externally.
    """
    if not log.entries or not log.entries.odata_id:
        logger.debug("Log %s has no Entries link", log.odata_id)
        return []

    return client._get_collection(log.entries.odata_id, LogEntry)
