"""
Base log-collect strategy and the generic (standard Redfish) implementation.

Vendor strategies inherit from :class:`BaseLogCollectStrategy` and customise
how diagnostic-data collection is triggered and how the produced bundle is
downloaded. Two levels of extension points are provided:

Low-level (standard ``#LogService.CollectDiagnosticData`` flow):
    - :meth:`build_body` — the request body.
    - :meth:`extract_download_uri` — where the artifact URI lives.

High-level (whole-flow override, for OEM schemes that don't fit the standard):
    - :meth:`discover_collect_target` — which URL to POST to trigger.
    - :meth:`build_collect_body` — the trigger request body.
    - :meth:`download_artifact` — how to fetch the finished bundle.

The generic strategy implements the standard DMTF flow; e.g. Inspur overrides
the high-level hooks to use a collection-level OEM ``CollectAllLog`` /
``DownloadAllLog`` pair.

The design mirrors ``update_strategies`` so the two multi-vendor features
share the same mental model: an abstract base, a generic fallback, a
registry of singletons, and runtime vendor detection.
"""
from __future__ import annotations

import logging
from abc import ABC
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.logs import LogEntry
from ...models.task import Task

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

# DMTF standard default diagnostic data type when the caller does not
# specify one and the vendor strategy has no OEM-preferred value.
DEFAULT_DIAGNOSTIC_DATA_TYPE = "Manager"

# Standard per-LogService collection action name.
COLLECT_ACTION = "#LogService.CollectDiagnosticData"


class BaseLogCollectStrategy(ABC):
    """
    Abstract base class for out-of-band log collection strategies.

    The default implementation follows the standard DMTF
    ``#LogService.CollectDiagnosticData`` flow. Vendors whose BMC uses a
    different scheme override the high-level hooks
    (:meth:`discover_collect_target`, :meth:`build_collect_body`,
    :meth:`download_artifact`).
    """

    #: Vendor-preferred diagnostic data type when the caller passes ``None``.
    #: ``None`` here means "fall back to the DMTF standard default".
    default_diagnostic_data_type: Optional[str] = None

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    def discover_collect_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        log_id: Optional[str],
    ) -> Optional[str]:
        """
        Return the action URL used to trigger collection, or ``None``.

        Standard behaviour: resolve a single LogService (auto-selecting the
        only one exposing ``CollectDiagnosticData`` when ``log_id`` is None)
        and return its action target. Vendors that publish a collection-level
        OEM action override this.
        """
        from .._log_helpers import _describe_services, resolve_log_service
        from ..systems import _extract_action_target
        from ...exceptions import RedfishValidationError, RedfishException
        from ...models.logs import Log

        if log_id is not None:
            log = resolve_log_service(client, log_services_odata_id, log_id)
            return _extract_action_target(log.actions, COLLECT_ACTION)

        services = client._get_collection(log_services_odata_id, Log)
        if not services:
            raise RedfishException(
                404, f"No log services found under {log_services_odata_id}"
            )
        if len(services) == 1:
            return _extract_action_target(services[0].actions, COLLECT_ACTION)

        supported = []
        for svc in services:
            if not svc.odata_id:
                continue
            try:
                full = client._http_client.get(svc.odata_id, Log)
            except RedfishException:
                continue
            if _extract_action_target(full.actions, COLLECT_ACTION):
                supported.append(full)

        if len(supported) == 1:
            logger.info(
                "Auto-selected log service %r for CollectDiagnosticData",
                supported[0].id,
            )
            return _extract_action_target(supported[0].actions, COLLECT_ACTION)
        if not supported:
            raise RedfishValidationError(
                f"No log service under {log_services_odata_id} exposes "
                f"{COLLECT_ACTION}. Available: {_describe_services(services)}"
            )
        raise RedfishValidationError(
            f"Multiple log services support CollectDiagnosticData, "
            f"please specify log_id. Candidates: {_describe_services(supported)}"
        )

    def resolve_diagnostic_data_type(
        self, diagnostic_data_type: Optional[str]
    ) -> str:
        """
        Resolve the effective ``DiagnosticDataType``.

        Priority: explicit caller value > vendor default > DMTF default.
        """
        if diagnostic_data_type:
            return diagnostic_data_type
        return self.default_diagnostic_data_type or DEFAULT_DIAGNOSTIC_DATA_TYPE

    def build_collect_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build the trigger request body. Standard: DMTF CollectDiagnosticData.
        """
        body: Dict[str, Any] = {
            "DiagnosticDataType": self.resolve_diagnostic_data_type(
                diagnostic_data_type
            ),
        }
        if oem_params:
            body.update(oem_params)
        return body

    # Backwards-compatible alias (older callers/tests used build_body).
    build_body = build_collect_body

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def extract_download_uri(
        self,
        client: "RedfishClient",
        task: Task,
    ) -> Optional[str]:
        """
        Locate the diagnostic-data artifact URI from a finished task.

        Standard behaviour reads the log entry referenced by the task and
        returns its ``AdditionalDataURI``. Returns ``None`` when unresolved.
        """
        entry = _resolve_task_log_entry(client, task)
        if entry is not None and entry.additional_data_uri:
            return entry.additional_data_uri
        return None

    def download_artifact(
        self,
        client: "RedfishClient",
        task: Task,
        output_path: Optional[str] = None,
    ) -> "bytes | str":
        """
        Download the produced bundle. Standard: resolve ``AdditionalDataURI``
        then GET it. Vendors with a POST-download action override this.

        Raises:
            RedfishValidationError: When no artifact URI can be resolved.
        """
        from ...exceptions import RedfishValidationError

        uri = self.extract_download_uri(client, task)
        if not uri:
            raise RedfishValidationError(
                "Could not resolve a diagnostic-data download URI "
                "(no AdditionalDataURI on the task or log entry)"
            )
        logger.info("Downloading diagnostic data from %s", uri)
        return client._http_client.download(uri, output_path)


class GenericLogCollectStrategy(BaseLogCollectStrategy):
    """
    Standard Redfish ``CollectDiagnosticData`` strategy (fallback).

    Used when the server vendor is not recognised. Sends the DMTF-standard
    body and reads ``AdditionalDataURI`` from the produced log entry.
    """


def _resolve_task_log_entry(
    client: "RedfishClient",
    task: Task,
) -> Optional[LogEntry]:
    """
    Best-effort resolution of the LogEntry a collection task produced.

    Strategy:
    1. If the task itself already carries ``AdditionalDataURI`` (some BMCs
       inline it), wrap it into a synthetic LogEntry.
    2. Otherwise inspect the task's ``Payload``/links for a log-entry link
       and GET it as a :class:`LogEntry`.

    Returns ``None`` when nothing can be resolved; callers then raise a
    descriptive error.
    """
    if task.odata_id:
        try:
            raw = client._http_client.get_raw(task.odata_id)
        except Exception:  # noqa: BLE001 — best-effort discovery
            raw = None
        if isinstance(raw, dict):
            uri = raw.get("AdditionalDataURI")
            if uri:
                return LogEntry.model_validate(raw)

            payload = raw.get("Payload") or {}
            target = payload.get("HttpOperation") and payload.get("TargetUri")
            entry_link = (
                raw.get("Links", {}).get("CreatedResources")
                or ([{"@odata.id": target}] if target else [])
            )
            for link in entry_link:
                link_id = link.get("@odata.id") if isinstance(link, dict) else None
                if link_id:
                    try:
                        return client._http_client.get(link_id, LogEntry)
                    except Exception:  # noqa: BLE001
                        continue
    return None
