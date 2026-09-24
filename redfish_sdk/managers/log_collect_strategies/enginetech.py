"""Enginetech (安擎) System BlackBox diagnostic-log strategy.

Enginetech exposes the standard ``CollectDiagnosticData`` action below a
ComputerSystem rather than below a Manager::

    Systems/{id}/LogServices/BlackBox/Actions/LogService.CollectDiagnosticData

The completed artifact is advertised by the fixed ``Latest`` LogEntry.  This
strategy keeps the SDK's public one-click API unchanged while adapting those
two resource-placement differences.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.logs import LogEntry
from ...models.task import Task
from .base import BaseLogCollectStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient


class EnginetechLogCollectStrategy(BaseLogCollectStrategy):
    """Collect and download Enginetech BlackBox diagnostic data."""

    default_diagnostic_data_type = "OEM"
    _LOG_SERVICE_ID = "BlackBox"
    _ENTRY_ID = "Latest"

    def resolve_log_services_odata_id(
        self,
        client: RedfishClient,
        manager_id: Optional[str] = None,
    ) -> str:
        """Discover the sole ComputerSystem's LogServices collection."""
        from .._log_helpers import require_log_services_link

        system = client.get_system()
        return require_log_services_link(system, f"System {system.id!r}")

    def build_collect_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the request accepted by Enginetech BlackBox."""
        body: Dict[str, Any] = {
            "DiagnosticDataType": self.resolve_diagnostic_data_type(
                diagnostic_data_type
            ),
            "OEMDiagnosticDataType": "BlackBox",
        }
        if oem_params:
            body.update(oem_params)
        return body

    def extract_download_uri(
        self,
        client: RedfishClient,
        task: Task,
    ) -> Optional[str]:
        """Read AdditionalDataURI from BlackBox/Entries/Latest."""
        from ...exceptions import RedfishValidationError
        from .._log_helpers import resolve_log_service

        log_services_odata_id = self.resolve_log_services_odata_id(client)
        log = resolve_log_service(
            client, log_services_odata_id, self._LOG_SERVICE_ID
        )
        entries_odata_id = (
            log.entries.odata_id if log.entries is not None else None
        )
        if not entries_odata_id:
            raise RedfishValidationError(
                "Enginetech BlackBox LogService has no Entries link"
            )

        entry_uri = f"{entries_odata_id.rstrip('/')}/{self._ENTRY_ID}"
        entry = client._http_client.get(entry_uri, LogEntry)
        if not entry.additional_data_uri:
            raise RedfishValidationError(
                f"Enginetech BlackBox entry {entry_uri} has no "
                "AdditionalDataURI"
            )
        return entry.additional_data_uri

    def find_existing_task(
        self,
        client: RedfishClient,
        log_services_odata_id: str,
        manager_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Always generate a fresh bundle because ``Latest`` is overwritten."""
        return None
