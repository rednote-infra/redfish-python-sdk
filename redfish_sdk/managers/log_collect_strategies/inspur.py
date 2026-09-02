"""
Inspur (浪潮) out-of-band log collection strategy.

Inspur BMCs (e.g. cs5280h3, OpenBmc-based) do NOT expose the standard
per-LogService ``#LogService.CollectDiagnosticData``. Instead the
``LogServices`` *collection* advertises OEM actions:

    #LogService.CollectAllLog   -> POST .../LogServices/Actions/Oem/Public/CollectAllLog
    #LogService.DownloadAllLog  -> POST .../LogServices/Actions/Oem/Public/DownloadAllLog

Observed flow (verified against a real cs5280h3 BMC):
    1. POST CollectAllLog with an empty body  -> HTTP 202 + a Task
    2. Poll the Task until Completed
    3. POST DownloadAllLog with an empty body -> HTTP 200 + the .tar.gz bundle
       directly in the body (Content-Disposition carries the filename, e.g.
       ``dump_8ME800499_20260902-1146.tar.gz``).

Reference: 各厂商 redfish 一键采集 — 浪潮
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.task import Task
from .base import BaseLogCollectStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

# Collection-level OEM action names published under LogServices.Actions.
_COLLECT_ACTION = "#LogService.CollectAllLog"
_DOWNLOAD_ACTION = "#LogService.DownloadAllLog"


class InspurLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for Inspur (浪潮) servers.

    Uses the collection-level ``CollectAllLog`` / ``DownloadAllLog`` OEM
    action pair instead of the standard per-LogService action.
    """

    def discover_collect_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        log_id: Optional[str],
    ) -> Optional[str]:
        """Return the collection-level ``CollectAllLog`` action target."""
        return self._collection_action_target(
            client, log_services_odata_id, _COLLECT_ACTION
        )

    def build_collect_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Inspur CollectAllLog takes an empty body (plus any oem_params)."""
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
        """POST ``DownloadAllLog`` and stream the returned .tar.gz bundle."""
        # The download action lives on the same collection as the task was
        # triggered from; re-discover it from the Manager LogServices.
        log_services_odata_id = self._task_log_services_hint(client, task)
        target = self._collection_action_target(
            client, log_services_odata_id, _DOWNLOAD_ACTION
        )
        if not target:
            from ...exceptions import RedfishValidationError

            raise RedfishValidationError(
                f"Inspur BMC does not expose {_DOWNLOAD_ACTION} on "
                f"{log_services_odata_id}"
            )
        logger.info("Inspur DownloadAllLog -> %s", target)
        return client._http_client.download_via_post(target, output_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collection_action_target(
        client: "RedfishClient",
        log_services_odata_id: str,
        action_name: str,
    ) -> Optional[str]:
        """Read an Actions target from the LogServices collection raw JSON."""
        raw = client._http_client.get_raw(log_services_odata_id)
        actions = raw.get("Actions") or {}
        action = actions.get(action_name) or {}
        target = action.get("target")
        return target if isinstance(target, str) and target else None

    @staticmethod
    def _task_log_services_hint(client: "RedfishClient", task: Task) -> str:
        """
        Best-effort LogServices collection path for the download action.

        Inspur triggers/downloads via the Manager LogServices collection, so
        default to Manager "1". Falls back to the standard Managers path.
        """
        try:
            return client._get_managers_collection_odata_id().rstrip("/") + "/1/LogServices"
        except Exception:  # noqa: BLE001
            return "/redfish/v1/Managers/1/LogServices"
