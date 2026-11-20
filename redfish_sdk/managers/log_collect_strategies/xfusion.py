"""
xFusion out-of-band log collection strategy.

1. POST ``Manager.Actions.Oem.xFusion["#Manager.Dump"]`` with
   ``{"Type": "URI", "Content": "/tmp/web/<name>.tar.gz"}``. The BMC writes
   the bundle on itself and the Task completes with ``iBMC.1.0.DumpingOK``.
   A single log (e.g. OperateLog) is exported the same way through that
   LogService's ``#LogService.ExportLog``.
2. POST ``Manager.Actions.Oem.xFusion["#Manager.GeneralDownload"]`` with
   ``{"TransferProtocol": "HTTPS", "Path": "/tmp/web/<name>.tar.gz"}``, which
   streams the file back as ``application/octet-stream``.

Both steps live behind :meth:`trigger` / :meth:`download_artifact`, so callers
keep using ``collect_and_download_diagnostic_data`` unchanged.
"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.task import Task
from .base import (
    BaseLogCollectStrategy,
    _format_failure_message,
    _merge_task_context,
    _serialise_messages,
)

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

DUMP_ACTION = "#Manager.Dump"
EXPORT_LOG_ACTION = "#LogService.ExportLog"
GENERAL_DOWNLOAD_ACTION = "#Manager.GeneralDownload"

#: Directory on the BMC that accepts generated artifacts.
CONTENT_DIR = "/tmp/web"


def _oem_action_target(oem: Optional[Dict[str, Any]], name: str) -> Optional[str]:
    """Return ``Actions.Oem.<vendor>.<name>.target`` from an OEM actions block."""
    for block in (oem or {}).values():
        node = block.get(name) if isinstance(block, dict) else None
        if isinstance(node, dict) and node.get("target"):
            return node["target"]
    return None


class XFusionLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for xFusion servers: OEM dump/export + general download.
    """

    def trigger(
        self,
        client: RedfishClient,
        log_services_odata_id: str,
        *,
        log_id: Optional[str] = None,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
        manager_id: Optional[str] = None,
    ) -> Task:
        """POST the OEM dump (or single-log export) action."""
        from ...exceptions import RedfishValidationError

        manager = client.get_manager(manager_id)
        manager_oem = manager.actions.oem if manager.actions else None
        if log_id:
            from .._log_helpers import resolve_log_service

            log = resolve_log_service(client, log_services_odata_id, log_id)
            log_actions = log.actions
            target = _oem_action_target(
                log_actions.get("Oem") if log_actions else None, EXPORT_LOG_ACTION
            )
            suffix = ".tar"
        else:
            target = _oem_action_target(manager_oem, DUMP_ACTION)
            suffix = ".tar.gz"
        if not target:
            raise RedfishValidationError(
                f"BMC exposes neither {DUMP_ACTION} nor "
                f"{EXPORT_LOG_ACTION} for log collection"
            )

        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        content = f"{CONTENT_DIR}/xf_sdk_{stamp}{suffix}"
        body = {"Type": "URI", "Content": content}
        logger.info("xFusion OEM collect POST %s body=%s", target, body)
        task = client._http_client.post(target, Task, raw_body=body)
        # Remember where the BMC writes the bundle; needed by the download step.
        task._xfusion_content = content
        return task

    def wait_until_ready(
        self,
        client: RedfishClient,
        task: Task,
        poll_interval: int = 5,
        timeout: int = 1800,
    ) -> Task:
        """Poll the Task resource until the dump reaches a terminal state.

        The Task URI from ``@odata.id`` is polled directly: the default waiter
        resolves a bare Task id through the Task collection, which iBMC answers
        with 5xx while a dump is running. The path the BMC writes to is only
        known from the trigger response, so it is carried onto the polled task
        for :meth:`download_artifact`.
        """
        from ...exceptions import LogCollectFailedError, RedfishException

        task_ref = task.odata_id
        if not task_ref:
            raise RedfishException(
                500,
                "xFusion dump did not return a Task URI; cannot poll for completion",
            )

        finished = client.wait_for_task(task_ref, poll_interval, timeout)
        state = finished.task_state or ""
        status = finished.task_status or ""
        if state != "Completed" or (status and status != "OK"):
            raise LogCollectFailedError(
                _format_failure_message(task_ref, state, status, finished.messages),
                task_id=str(finished.id or task_ref),
                task_state=state,
                task_status=status,
                messages=_serialise_messages(finished.messages),
            )
        finished = _merge_task_context(task, finished)
        finished._xfusion_content = getattr(task, "_xfusion_content", None)
        return finished

    def download_artifact(
        self,
        client: RedfishClient,
        task: Task,
        output_path: Optional[str] = None,
    ) -> bytes | str:
        """POST ``#Manager.GeneralDownload`` for the artifact the BMC wrote."""
        from ...exceptions import RedfishValidationError

        content = getattr(task, "_xfusion_content", None)
        if not content:
            raise RedfishValidationError(
                "xFusion log artifact path is missing; trigger a collection first"
            )

        manager = client.get_manager(None)
        target = _oem_action_target(
            manager.actions.oem if manager.actions else None, GENERAL_DOWNLOAD_ACTION
        )
        if not target:
            raise RedfishValidationError(
                f"xFusion BMC does not expose {GENERAL_DOWNLOAD_ACTION}; "
                f"cannot fetch the artifact at {content}"
            )
        body = {"TransferProtocol": "HTTPS", "Path": content}
        logger.info("xFusion GeneralDownload POST %s body=%s", target, body)
        return client._http_client.download_via_post(
            target, output_path, raw_body=body
        )
