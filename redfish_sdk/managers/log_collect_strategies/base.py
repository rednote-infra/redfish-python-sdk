"""
Base log-collect strategy and the generic (standard Redfish) implementation.

All vendor-specific strategies inherit from :class:`BaseLogCollectStrategy`
and override :meth:`build_body` (to construct the vendor-appropriate
``#LogService.CollectDiagnosticData`` request body) and, when required,
:meth:`extract_download_uri` (to locate the produced artifact URI on a
finished collection task).

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


class BaseLogCollectStrategy(ABC):
    """
    Abstract base class for out-of-band log collection strategies.

    Subclasses customise two extension points:

    - :meth:`build_body` — the ``CollectDiagnosticData`` request body.
    - :meth:`extract_download_uri` — where the artifact URI lives on the
      finished task's associated log entry (defaults to the standard
      ``AdditionalDataURI``).
    """

    #: Vendor-preferred diagnostic data type when the caller passes ``None``.
    #: ``None`` here means "fall back to the DMTF standard default".
    default_diagnostic_data_type: Optional[str] = None

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

    def build_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build the standard DMTF ``CollectDiagnosticData`` request body.

        Args:
            diagnostic_data_type: Requested ``DiagnosticDataType`` or ``None``
                to use the resolved default.
            oem_params: Optional dict shallow-merged into the body so callers
                can pass OEM fields without a dedicated vendor strategy.

        Returns:
            The request body dict.
        """
        body: Dict[str, Any] = {
            "DiagnosticDataType": self.resolve_diagnostic_data_type(
                diagnostic_data_type
            ),
        }
        if oem_params:
            body.update(oem_params)
        return body

    def extract_download_uri(
        self,
        client: "RedfishClient",
        task: Task,
    ) -> Optional[str]:
        """
        Locate the diagnostic-data artifact URI from a finished task.

        The standard behaviour reads the log entry referenced by the task's
        ``Payload``/associated resource and returns its ``AdditionalDataURI``.
        Vendors that expose the artifact elsewhere override this method.

        Returns ``None`` when no artifact URI can be resolved.
        """
        entry = _resolve_task_log_entry(client, task)
        if entry is not None and entry.additional_data_uri:
            return entry.additional_data_uri
        return None


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
    2. Otherwise inspect the task's ``Oem``/raw payload for a log-entry link
       and GET it as a :class:`LogEntry`.

    Returns ``None`` when nothing can be resolved; callers then raise a
    descriptive error.
    """
    # 1. Some BMCs put AdditionalDataURI directly on the task's raw body.
    if task.odata_id:
        try:
            raw = client._http_client.get_raw(task.odata_id)
        except Exception:  # noqa: BLE001 — best-effort discovery
            raw = None
        if isinstance(raw, dict):
            uri = raw.get("AdditionalDataURI")
            if uri:
                return LogEntry.model_validate(raw)

            # 2. Follow a linked log entry when advertised.
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
