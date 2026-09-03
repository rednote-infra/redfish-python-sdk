"""
Lenovo (联想) out-of-band log collection strategy.

Lenovo servers (observed on AMI MegaRAC-based BMCs, e.g. root Oem = ``Ami``)
publish three OEM actions on the ``LogServices`` collection — the trigger
returns a plain ``{"Oem":{"Public":{"Status":0}}}`` response (NOT a Redfish
Task), and progress is polled on a bespoke GET-only endpoint::

    #LogService.CollectAllLog          POST -> HTTP 200 + Status:0
    #LogService.GetLogCollectProgress  GET  -> {"Oem":{"Public":{"Progress":N,"Status":0}}}
    #LogService.DownloadAllLog         POST -> binary bundle (Content-Disposition)

Observed flow (verified end-to-end against a real Lenovo BMC 10.27.97.152):
    1. POST CollectAllLog (empty body)   → HTTP 200, ``Status:0`` means accepted.
    2. Poll CollectProgress until ``Progress >= 100``.
    3. POST DownloadAllLog (empty body)  → binary bundle in the body,
       filename in ``Content-Disposition``.

Similar to :class:`InspurLogCollectStrategy` in overall shape, but uses a
private progress endpoint (like ZTE) instead of a standard TaskService.

Reference: 各厂商 redfish 一键采集 — Lenovo (AMI-based)
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.task import Task
from .base import BaseLogCollectStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

# Collection-level OEM action names published under LogServices.Actions.Oem.
_COLLECT_ACTION = "#LogService.CollectAllLog"
_DOWNLOAD_ACTION = "#LogService.DownloadAllLog"
_PROGRESS_ACTION = "#LogService.GetLogCollectProgress"


class LenovoLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for Lenovo servers (AMI MegaRAC-based BMCs).

    Uses the collection-level ``CollectAllLog`` / ``DownloadAllLog`` OEM
    action pair with a private ``CollectProgress`` GET endpoint for waiting.
    """

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    def discover_collect_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        log_id: Optional[str],
    ) -> Optional[str]:
        """Return the collection-level OEM ``CollectAllLog`` action target."""
        return self._collection_action_target(
            client, log_services_odata_id, _COLLECT_ACTION
        )

    def build_collect_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Lenovo CollectAllLog takes an empty body (plus any oem_params)."""
        body: Dict[str, Any] = {}
        if oem_params:
            body.update(oem_params)
        return body

    def trigger(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        *,
        log_id: Optional[str] = None,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
        manager_id: str = "1",
    ) -> Task:
        """
        POST CollectAllLog and return a synthetic Task carrying the URLs
        needed to poll progress and download the bundle.

        The trigger response is a plain success message, not a Task, so we
        fabricate one so downstream logic in
        ``ManagersManager.collect_and_download_diagnostic_data`` doesn't
        need a Lenovo-specific branch.
        """
        from ...exceptions import RedfishValidationError
        from ...models.common import RedfishResponse

        collect_target = self._collection_action_target(
            client, log_services_odata_id, _COLLECT_ACTION
        )
        progress_target = self._collection_action_target(
            client, log_services_odata_id, _PROGRESS_ACTION
        )
        download_target = self._collection_action_target(
            client, log_services_odata_id, _DOWNLOAD_ACTION
        )
        if not (collect_target and progress_target and download_target):
            raise RedfishValidationError(
                f"Lenovo BMC does not expose the full Collect/Progress/"
                f"Download OEM action trio on {log_services_odata_id}: "
                f"collect={collect_target!r}, progress={progress_target!r}, "
                f"download={download_target!r}"
            )
        body = self.build_collect_body(diagnostic_data_type, oem_params)
        logger.info("Lenovo CollectAllLog POST %s body=%s", collect_target, body)
        client._http_client.post(collect_target, RedfishResponse, raw_body=body)

        return Task.model_construct(
            id="lenovo-collect",
            task_state="Running",
            _lenovo_progress_url=progress_target,
            _lenovo_download_url=download_target,
        )

    # ------------------------------------------------------------------
    # Wait (bespoke Oem.Public.Progress endpoint, not TaskService)
    # ------------------------------------------------------------------

    def wait_until_ready(
        self,
        client: "RedfishClient",
        task: Task,
        poll_interval: int = 5,
        timeout: int = 1800,
    ) -> Task:
        """Poll ``CollectProgress`` until ``Oem.Public.Progress >= 100``."""
        from ...exceptions import LogCollectFailedError, RedfishException
        from ...models.log_collect import LenovoCollectProgress

        progress_url = getattr(task, "_lenovo_progress_url", None)
        if not progress_url:
            raise RedfishException(
                500, "Lenovo progress URL missing on the collection task"
            )

        step = max(int(poll_interval), 1)
        elapsed = 0
        history: list = []
        last_progress: Optional[int] = None
        while elapsed < timeout:
            prog = client._http_client.get(progress_url, LenovoCollectProgress)
            history.append(prog.snapshot())
            last_progress = prog.progress
            logger.info(
                "Lenovo CollectProgress: progress=%s status=%s",
                prog.progress, prog.status,
            )
            if prog.is_done():
                # Status:0 == OK on this BMC firmware; anything else is a
                # vendor-defined failure signal.
                if prog.status is not None and prog.status != 0:
                    raise LogCollectFailedError(
                        f"Lenovo diagnostic collection finished with "
                        f"non-OK status={prog.status!r}",
                        task_id=str(task.id or "lenovo-collect"),
                        task_state="Exception",
                        task_status=str(prog.status),
                        progress_history=history,
                    )
                task.task_state = "Completed"
                return task
            time.sleep(step)
            elapsed += step

        raise LogCollectFailedError(
            f"Lenovo diagnostic collection did not complete within {timeout}s "
            f"(last progress={last_progress!r})",
            task_id=str(task.id or "lenovo-collect"),
            task_state="Running",
            progress_history=history,
        )

    # ------------------------------------------------------------------
    # Download (DownloadAllLog with an empty body)
    # ------------------------------------------------------------------

    def download_artifact(
        self,
        client: "RedfishClient",
        task: Task,
        output_path: Optional[str] = None,
    ) -> "bytes | str":
        """POST ``DownloadAllLog`` and stream the returned bundle to disk."""
        from ...exceptions import RedfishValidationError

        download_target = getattr(task, "_lenovo_download_url", None)
        if not download_target:
            raise RedfishValidationError(
                "Lenovo download URL missing on the collection task"
            )
        logger.info("Lenovo DownloadAllLog -> %s", download_target)
        return client._http_client.download_via_post(download_target, output_path)

    # ------------------------------------------------------------------
    # Existing-task discovery
    # ------------------------------------------------------------------

    def find_existing_task(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        manager_id: str = "1",
    ) -> Optional[Task]:
        """
        Lenovo does not surface prior collections through TaskService, and
        (like Inspur) the bundle path is transient: the BMC regenerates it
        on every ``CollectAllLog`` trigger. Reusing a "prior" task would
        just download whatever tail state the BMC last wrote, which is
        confusing at best. Force a fresh collection every time.
        """
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collection_action_target(
        client: "RedfishClient",
        log_services_odata_id: str,
        action_name: str,
    ) -> Optional[str]:
        """
        Resolve a collection-level OEM action via
        :meth:`LogServicesCollection.oem_action`. Lenovo puts the trio under
        ``Actions.Oem.<action>`` — the second of the three layouts already
        supported.
        """
        from ...models.log_collect import LogServicesCollection

        collection = client._http_client.get(
            log_services_odata_id, LogServicesCollection
        )
        action = collection.oem_action(action_name)
        return action.target if action else None
