"""
ZTE (中兴) out-of-band log collection strategy.

ZTE BMCs do NOT use the standard per-LogService ``CollectDiagnosticData`` nor
a Redfish TaskService flow. Instead the ``LogServices`` *collection* exposes
OEM actions under ``Actions.Oem`` and progress is tracked on a bespoke
endpoint:

    #LogServices.Dump          -> POST .../LogServices/Actions/LogServices.Dump
    #LogServices.Dump/Progress -> GET  .../LogServices/Actions/LogServices.Dump/Progress
    #Manager.GeneralDownload   -> POST .../Managers/Self/Actions/Manager.GeneralDownload

Observed flow (verified against a real BMC):
    1. POST Dump  body={"Type": "AllLogs"}  -> HTTP 200 (Base.1.8.1.Success);
       NOT a Redfish Task.
    2. GET Dump/Progress -> {"State", "Percentage", "TarPath", "Type"}.
       Poll until State == "STATE_COMPLETED"; TarPath is the produced file.
    3. POST GeneralDownload body={"Path": <TarPath>} -> the bundle bytes.

Because the trigger response is not a Redfish Task, this strategy returns a
*synthetic* Task carrying the progress URL / manager id it needs later, and
overrides ``wait_until_ready`` to poll the OEM progress endpoint.

Reference: 各厂商 redfish 一键采集 — 中兴
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

_DUMP_ACTION = "#LogServices.Dump"
_DEFAULT_TYPE = "AllLogs"
# Terminal progress states.
_DONE_STATES = {"STATE_COMPLETED", "STATE_SUCCESS", "STATE_FINISH"}
_FAIL_STATES = {"STATE_FAILED", "STATE_ERROR"}


class ZteLogCollectStrategy(BaseLogCollectStrategy):
    """Log-collect strategy for ZTE (中兴) servers."""

    default_diagnostic_data_type = _DEFAULT_TYPE

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    def discover_collect_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        log_id: Optional[str],
    ) -> Optional[str]:
        """Return the collection-level OEM ``LogServices.Dump`` target."""
        from ...models.log_collect import LogServicesCollection

        collection = client._http_client.get(
            log_services_odata_id, LogServicesCollection
        )
        action = collection.oem_action(_DUMP_ACTION)
        return action.target if action else None

    def build_collect_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"Type": diagnostic_data_type or _DEFAULT_TYPE}
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
        """POST Dump and return a synthetic Task carrying progress context."""
        from ...exceptions import RedfishValidationError
        from ...models.common import RedfishResponse

        target = self.discover_collect_target(
            client, log_services_odata_id, log_id
        )
        if not target:
            raise RedfishValidationError(
                f"ZTE BMC does not expose {_DUMP_ACTION} under "
                f"{log_services_odata_id}"
            )
        body = self.build_collect_body(diagnostic_data_type, oem_params)
        logger.info("ZTE Dump trigger POST %s body=%s", target, body)
        # Dump returns a success message, not a Task; ignore the parsed body.
        client._http_client.post(target, RedfishResponse, raw_body=body)

        progress_url = f"{target}/Progress"
        # Stash context on the synthetic Task (Entity allows extra fields).
        return Task.model_construct(
            id="zte-dump",
            task_state="Running",
            _zte_progress_url=progress_url,
            _zte_manager_id=manager_id,
        )

    # ------------------------------------------------------------------
    # Existing-task discovery (via Dump/Progress, not TaskService)
    # ------------------------------------------------------------------

    def find_existing_task(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        manager_id: str = "1",
    ) -> Optional[Task]:
        """
        Probe ``Dump/Progress`` for a reusable collection.

        - ``State`` in DONE + valid ``TarPath`` → synthetic Task marked
          ``Completed`` with ``_zte_tar_path`` set, so the caller can skip
          straight to download.
        - Non-terminal (Running / preparing) → synthetic Task marked
          ``Running`` carrying the progress URL, so the caller can just wait.
        - ``State`` in FAIL or missing → return ``None`` (no reuse; a fresh
          collection should be triggered).
        """
        from ...exceptions import RedfishException

        from ...models.log_collect import ZteDumpProgress

        target = self.discover_collect_target(
            client, log_services_odata_id, log_id=None
        )
        if not target:
            return None
        progress_url = f"{target}/Progress"
        try:
            prog = client._http_client.get(progress_url, ZteDumpProgress)
        except RedfishException:
            return None

        state = prog.state or ""
        if state in _DONE_STATES and prog.is_valid_tar_path():
            logger.info(
                "ZTE find_existing_task: reusing completed collection tar=%s",
                prog.tar_path,
            )
            return Task.model_construct(
                id="zte-dump",
                task_state="Completed",
                _zte_progress_url=progress_url,
                _zte_manager_id=manager_id,
                _zte_tar_path=prog.tar_path,
            )
        if state and state not in _FAIL_STATES:
            logger.info(
                "ZTE find_existing_task: reusing in-flight collection (state=%s)",
                state,
            )
            return Task.model_construct(
                id="zte-dump",
                task_state="Running",
                _zte_progress_url=progress_url,
                _zte_manager_id=manager_id,
            )
        return None

    # ------------------------------------------------------------------
    # Wait (bespoke progress endpoint, not TaskService)
    # ------------------------------------------------------------------

    def wait_until_ready(
        self,
        client: "RedfishClient",
        task: Task,
        poll_interval: int = 5,
        timeout: int = 1800,
    ) -> Task:
        """Poll the OEM ``Dump/Progress`` endpoint until completion."""
        from ...exceptions import LogCollectFailedError, RedfishException
        from ...models.log_collect import ZteDumpProgress

        progress_url = getattr(task, "_zte_progress_url", None)
        if not progress_url:
            raise RedfishException(
                500, "ZTE progress URL missing on the collection task"
            )

        # Guard against 0 poll_interval causing a busy loop.
        step = max(int(poll_interval), 1)
        elapsed = 0
        tar_path: Optional[str] = None
        iteration = 0
        history: list = []
        while elapsed < timeout:
            prog = client._http_client.get(progress_url, ZteDumpProgress)
            state = prog.state or ""
            pct = prog.percentage
            tar_path = prog.tar_path or tar_path
            history.append(prog.snapshot())
            logger.info(
                "ZTE Dump progress: state=%s percent=%s tar=%s",
                state, pct, tar_path,
            )
            if state in _DONE_STATES or str(pct) == "100":
                task._zte_tar_path = tar_path  # type: ignore[attr-defined]
                task.task_state = "Completed"
                return task
            # Ignore a stale STATE_FAILED reading on the very first poll (the
            # BMC often keeps the previous run's terminal state until the new
            # task takes over); treat it as terminal on the second read.
            if state in _FAIL_STATES and iteration > 0:
                raise LogCollectFailedError(
                    f"ZTE diagnostic collection failed: state={state!r}, "
                    f"message={prog.message!r} (tar_path={tar_path!r})",
                    task_id=str(task.id or "zte-dump"),
                    task_state=state,
                    task_status=prog.message or "",
                    progress_history=history,
                )
            time.sleep(step)
            elapsed += step
            iteration += 1

        raise LogCollectFailedError(
            f"ZTE diagnostic collection did not complete within {timeout}s "
            f"(last state={history[-1]['state'] if history else 'unknown'!r})",
            task_id=str(task.id or "zte-dump"),
            task_state=history[-1]["state"] if history else "",
            progress_history=history,
        )

    # ------------------------------------------------------------------
    # Download (GeneralDownload with the produced TarPath)
    # ------------------------------------------------------------------

    def download_artifact(
        self,
        client: "RedfishClient",
        task: Task,
        output_path: Optional[str] = None,
    ) -> "bytes | str":
        """POST ``Manager.GeneralDownload`` with the TarPath from progress."""
        from ...exceptions import RedfishValidationError
        from ...models.log_collect import ZteDumpProgress

        tar_path = getattr(task, "_zte_tar_path", None)
        if not tar_path:
            # Fall back to reading progress once more.
            progress_url = getattr(task, "_zte_progress_url", None)
            if progress_url:
                prog = client._http_client.get(progress_url, ZteDumpProgress)
                tar_path = prog.tar_path
        if not tar_path:
            raise RedfishValidationError(
                "ZTE download failed: no TarPath resolved from Dump/Progress"
            )

        manager_id = getattr(task, "_zte_manager_id", "1") or "1"
        download_target = self._general_download_target(client, manager_id)
        logger.info(
            "ZTE GeneralDownload POST %s Path=%s", download_target, tar_path
        )
        return client._http_client.download_via_post(
            download_target, output_path, raw_body={"Path": tar_path}
        )

    @staticmethod
    def _general_download_target(client: "RedfishClient", manager_id: str) -> str:
        """
        Discover ``#Manager.GeneralDownload`` target from the Manager.

        ZTE uses ``/redfish/v1/Managers/Self``; rather than trusting the
        caller-supplied ``manager_id`` (which defaults to "1"), resolve the
        actual Manager from the collection's first member.
        """
        from ...models.common import Collection
        from ...models.managers import Manager

        managers_col_url = client._get_managers_collection_odata_id().rstrip("/")
        col = client._http_client.get(managers_col_url, Collection[Manager])
        members = col.members or []
        manager_url = (
            members[0].odata_id
            if members and members[0].odata_id
            else f"{managers_col_url}/{manager_id}"
        )
        manager = client._http_client.get(manager_url, Manager)
        actions = manager.actions or {}
        action = actions.get("#Manager.GeneralDownload") or {}
        target = action.get("target") if isinstance(action, dict) else None
        if isinstance(target, str) and target:
            return target
        return f"{manager_url}/Actions/Manager.GeneralDownload"
