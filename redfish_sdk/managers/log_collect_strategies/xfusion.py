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
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.task import Task
from .base import BaseLogCollectStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

DUMP_ACTION = "#Manager.Dump"
EXPORT_LOG_ACTION = "#LogService.ExportLog"
GENERAL_DOWNLOAD_ACTION = "#Manager.GeneralDownload"

#: Directory on the BMC that accepts generated artifacts.
CONTENT_DIR = "/tmp/web"


def _action_target(actions: Optional[Dict[str, Any]], name: str) -> Optional[str]:
    """Return ``Actions.Oem.<vendor>.<name>.target`` from a raw resource."""
    for inner in ((actions or {}).get("Oem") or {}).values():
        node = inner.get(name) if isinstance(inner, dict) else None
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

        manager_raw = client._http_client.get_raw(
            client.get_manager(manager_id).odata_id
        )
        if log_id:
            from .._log_helpers import resolve_log_service

            log = resolve_log_service(client, log_services_odata_id, log_id)
            target = _action_target(
                (client._http_client.get_raw(log.odata_id) or {}).get("Actions"),
                EXPORT_LOG_ACTION,
            )
            suffix = ".tar"
        else:
            target = _action_target(manager_raw.get("Actions"), DUMP_ACTION)
            suffix = ".tar.gz"
        if not target:
            raise RedfishValidationError(
                f"xBMC exposes neither {DUMP_ACTION} nor "
                f"{EXPORT_LOG_ACTION} for log collection"
            )

        content = "%s/xf_sdk_%s%s" % (
            CONTENT_DIR,
            datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
            suffix,
        )
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
        """Poll the task resource until the dump finishes.

        Reads the raw JSON: iBMC reports ``PercentComplete`` as ``"100%"``,
        which the strict ``Task`` model rejects.
        """
        from ...exceptions import LogCollectFailedError

        target = task.odata_id or task.id
        deadline = time.monotonic() + timeout
        state = status = ""
        messages: list = []
        while time.monotonic() < deadline:
            raw = client._http_client.get_raw(target)
            state = raw.get("TaskState") or ""
            status = raw.get("TaskStatus") or ""
            messages = raw.get("Messages") or []
            if state in ("Completed", "Exception", "Killed", "Cancelled"):
                break
            time.sleep(poll_interval)
        if state != "Completed" or (status and status != "OK"):
            detail = "; ".join(
                f"{m.get('MessageId', '')}: {m.get('Message', '')}"
                for m in messages
                if isinstance(m, dict)
            )
            raise LogCollectFailedError(
                f"Diagnostic collection task {target} did not succeed: "
                f"state={state!r}, status={status!r} | {detail}",
                task_id=str(target),
                task_state=state,
                task_status=status,
            )
        return task

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
        target = _action_target(
            (client._http_client.get_raw(manager.odata_id) or {}).get("Actions"),
            GENERAL_DOWNLOAD_ACTION,
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
