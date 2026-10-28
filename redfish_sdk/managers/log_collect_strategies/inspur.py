"""
Inspur (浪潮) out-of-band log collection strategy.

Inspur-compatible BMCs (including IEIT SYSTEMS) do NOT expose the standard
per-LogService ``#LogService.CollectDiagnosticData``. Instead the Manager
``LogServices`` collection or one of its members advertises OEM actions:

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

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.task import Task
from .base import BaseLogCollectStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

# OEM action names published on the collection or a LogService member.
_COLLECT_ACTION = "#LogService.CollectAllLog"
_DOWNLOAD_ACTION = "#LogService.DownloadAllLog"


class InspurLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for Inspur and compatible IEIT SYSTEMS servers.

    Uses the Manager LogServices ``CollectAllLog`` / ``DownloadAllLog`` OEM
    action pair instead of the standard per-LogService action. Descriptors may
    live on either the collection root or an advertised member.
    """

    def find_existing_task(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        manager_id: Optional[str] = None,
    ) -> Optional[Task]:
        """
        Inspur never reuses a prior task — the collection artifact is written
        to a fixed BMC path (``/tmp/onekeylog.tar.gz``) and overwritten /
        purged between runs, so a "Completed" Task on the BMC does NOT imply
        the artifact still exists (verified on cs5280h3: reusing a prior
        task and calling DownloadAllLog returns 404
        ``Base.1.13.0.ResourceNotFound`` for the tar.gz).

        Returning ``None`` forces
        :meth:`ManagersManager.collect_and_download_diagnostic_data` to
        trigger a fresh collection, which regenerates the file first.
        """
        return None

    def discover_collect_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        log_id: Optional[str],
    ) -> Optional[str]:
        """Return the advertised ``CollectAllLog`` action target."""
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
        """
        Read an OEM ``ActionTarget`` from a LogServices collection or member.

        Inspur publishes the collection-level action either directly under
        ``Actions.Oem`` (``{"Oem": {"#LogService.CollectAllLog": {...}}}``)
        or nested under a vendor sub-key such as ``Public``
        (``{"Oem": {"Public": {"#LogService.CollectAllLog": {...}}}}``).
        :meth:`LogServicesCollection.oem_action` handles both shapes. Some
        IEIT SYSTEMS firmwares advertise the same action pair only on the
        ``Public`` LogService member, so the advertised members are checked
        when the collection root has no matching action.
        """
        from ...exceptions import RedfishException
        from ...models.log_collect import LogServicesCollection
        from ...models.logs import Log

        collection = client._http_client.get(
            log_services_odata_id, LogServicesCollection
        )
        action = collection.oem_action(action_name)
        if action and action.target:
            return action.target

        for member in collection.members:
            if not member.odata_id:
                continue
            try:
                log_service = client._http_client.get(member.odata_id, Log)
            except RedfishException as exc:
                logger.debug(
                    "Skipping LogService %s during Inspur action discovery: %s",
                    member.odata_id,
                    exc,
                )
                continue
            actions = (
                log_service.actions.model_dump(
                    by_alias=True, exclude_none=True
                )
                if log_service.actions
                else None
            )
            member_view = LogServicesCollection.model_construct(actions=actions)
            action = member_view.oem_action(action_name)
            if action and action.target:
                logger.info(
                    "Discovered %s on LogService member %s",
                    action_name,
                    member.odata_id,
                )
                return action.target
        return None

    @staticmethod
    def _task_log_services_hint(client: "RedfishClient", task: Task) -> str:
        """
        Return the advertised Manager LogServices collection path for the
        download action.
        """
        from .._log_helpers import require_log_services_link

        manager = client.get_manager()
        return require_log_services_link(manager, f"Manager {manager.id!r}")


class IeitLogCollectStrategy(InspurLogCollectStrategy):
    """Inspur-compatible flow with IEIT's reusable, eventually visible tasks."""

    def find_existing_task(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        manager_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Reuse an in-flight IEIT task instead of starting a duplicate."""
        task = BaseLogCollectStrategy.find_existing_task(
            self, client, log_services_odata_id, manager_id
        )
        if task is None:
            return None
        state = (task.task_state or "").lower()
        if state in {"completed", "exception", "killed", "cancelled"}:
            return None
        return task

    def wait_until_ready(
        self,
        client: "RedfishClient",
        task: Task,
        poll_interval: int = 5,
        timeout: int = 1800,
    ) -> Task:
        """Wait for an IEIT task while tolerating its visibility delay."""
        from ...exceptions import RedfishException

        task_id = None
        if task.odata_id:
            task_id = task.odata_id.rstrip("/").rsplit("/", 1)[-1]
        task_id = task_id or task.id
        if not task_id:
            raise RedfishException(
                500,
                "Collection did not return a Task id; cannot poll for completion",
            )

        step = max(float(poll_interval), 0.001)
        elapsed = 0.0
        while elapsed < timeout:
            try:
                visible = (
                    client._http_client.get(task.odata_id, Task)
                    if task.odata_id
                    else client.get_task(str(task_id))
                )
            except RedfishException as exc:
                if not self._is_task_visibility_delay(exc):
                    raise
                logger.info(
                    "IEIT Task %s is not visible yet; retrying in %ss",
                    task_id,
                    step,
                )
                time.sleep(step)
                elapsed += step
                continue

            logger.info(
                "IEIT Task %s is visible: state=%s, percent=%s%%",
                task_id,
                visible.task_state,
                visible.percent_complete,
            )
            remaining = max(timeout - elapsed, step)
            return super().wait_until_ready(
                client,
                visible,
                poll_interval=poll_interval,
                timeout=remaining,
            )

        raise TimeoutError(
            f"Task {task_id} did not complete within {timeout} seconds"
        )

    @staticmethod
    def _is_task_visibility_delay(exc: Exception) -> bool:
        """Return whether IEIT reported its transient no-running-task code."""
        from ...exceptions import RedfishException

        if not isinstance(exc, RedfishException) or exc.status_code != 500:
            return False
        try:
            body = json.loads(exc.body or "{}")
        except (TypeError, ValueError):
            return False
        return body.get("code") == 17017
