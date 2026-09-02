"""
smoothcompute (顺算) out-of-band log collection strategy.

smoothcompute BMCs (observed on the 6415 X2 family) do NOT publish the
standard ``#LogService.CollectDiagnosticData`` action on any LogService.
Instead an OEM ``DiagnosticService`` on the Manager exposes a two-action
"black-box" collection pair, and the trigger returns a *standard* Redfish
Task so we can reuse ``wait_for_task`` / ``wait_until_ready`` unchanged.

Observed flow (verified end-to-end against a real 6415 X2 BMC):
    1. POST /redfish/v1/Managers/{id}/DiagnosticService/Actions/
            DiagnosticService.CollectBlackBox
       (empty body) -> HTTP 200 + Task ({Id, TaskState=Running,
       Oem.BMC.ProgressMessage})
    2. Poll /redfish/v1/TaskService/Tasks/{Id} until TaskState=Completed
       (~15s on the tested BMC; PercentComplete progresses monotonically)
    3. POST /redfish/v1/Managers/{id}/DiagnosticService/Actions/
            DiagnosticService.ExportBlackBox
       (empty body) -> HTTP 200 + binary zip.gz with a descriptive
       Content-Disposition filename (e.g.
       ``6415_X2_9800216104486830_20260902-0943.zip.gz`` — product, SN,
       timestamp).

Reference: 各厂商 redfish 一键采集 — smoothcompute (Vendor="smoothcompute",
Product="6415 X2")
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.task import Task
from .base import BaseLogCollectStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

# OEM Manager sub-resource + its two collection actions.
_DIAG_SUBPATH = "DiagnosticService"
_COLLECT_ACTION = "#DiagnosticService.CollectBlackInfo"
_DOWNLOAD_ACTION = "#DiagnosticService.DownloadBlackInfo"


class SmoothcomputeLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for smoothcompute (顺算) servers.

    Trigger + download live on ``Manager.Oem.BMC.DiagnosticService``; the
    trigger response is a standard Redfish Task, so wait / progress reuse
    the base ``wait_until_ready`` (TaskService polling) unchanged.
    """

    def discover_collect_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        log_id: Optional[str],
    ) -> Optional[str]:
        """Return the ``DiagnosticService.CollectBlackBox`` action target."""
        return self._diag_action_target(
            client, log_services_odata_id, _COLLECT_ACTION
        )

    def build_collect_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """CollectBlackBox takes an empty body (plus any oem_params)."""
        body: Dict[str, Any] = {}
        if oem_params:
            body.update(oem_params)
        return body

    def download_artifact(
        self,
        client: "RedfishClient",
        task: Task,
        output_path: Optional[str] = None,
    ) -> "bytes | str":
        """POST ``DiagnosticService.ExportBlackBox`` and stream the bundle."""
        from ...exceptions import RedfishValidationError

        # The download action lives on the same DiagnosticService the trigger
        # ran under; discover it from the same Manager the task belongs to.
        manager_url = self._task_manager_url(client, task)
        target = self._diag_action_target_via_manager(
            client, manager_url, _DOWNLOAD_ACTION
        )
        if not target:
            raise RedfishValidationError(
                f"smoothcompute BMC does not expose {_DOWNLOAD_ACTION} on "
                f"{manager_url}/{_DIAG_SUBPATH}"
            )
        logger.info("smoothcompute ExportBlackBox -> %s", target)
        return client._http_client.download_via_post(target, output_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _diag_action_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        action_name: str,
    ) -> Optional[str]:
        """
        Resolve DiagnosticService (a Manager sub-resource) from the
        LogServices link the caller gave us: strip the trailing
        "/LogServices" to get the Manager URL, then follow to
        Manager/DiagnosticService.
        """
        manager_url = log_services_odata_id.rstrip("/")
        if manager_url.endswith("/LogServices"):
            manager_url = manager_url[: -len("/LogServices")]
        return self._diag_action_target_via_manager(
            client, manager_url, action_name
        )

    @staticmethod
    def _diag_action_target_via_manager(
        client: "RedfishClient",
        manager_url: str,
        action_name: str,
    ) -> Optional[str]:
        from ...exceptions import RedfishException

        diag_url = f"{manager_url.rstrip('/')}/{_DIAG_SUBPATH}"
        try:
            raw = client._http_client.get_raw(diag_url)
        except RedfishException as exc:
            logger.warning("GET %s failed: %s", diag_url, exc)
            return None
        actions = raw.get("Actions") or {}
        action = actions.get(action_name) or {}
        target = action.get("target")
        return target if isinstance(target, str) and target else None

    @staticmethod
    def _task_manager_url(client: "RedfishClient", task: Task) -> str:
        """
        Best-effort Manager URL the DiagnosticService lives under.

        Uses the Managers collection's first member (matches this BMC's
        single-Manager layout — id="1"). Falls back to
        ``/redfish/v1/Managers/1``.
        """
        try:
            col = client._http_client.get_raw(
                client._get_managers_collection_odata_id()
            )
            members = col.get("Members") or []
            if members and isinstance(members[0], dict):
                mid = members[0].get("@odata.id")
                if mid:
                    return mid
        except Exception:  # noqa: BLE001 — best-effort
            pass
        return "/redfish/v1/Managers/1"
