"""H3C (新华三) SDS diagnostic-log collection strategy.

H3C HDM does not expose the standard per-LogService
``#LogService.CollectDiagnosticData`` action.  The Manager instead publishes
OEM ``Manager.Dump`` and ``Manager.GeneralDownload`` actions.  Collection
creates an asynchronous Redfish Task; after it completes, the SDS archive is
downloaded with a second POST.

Observed on H3C HDM firmware 2.09, ``#Manager.GeneralDownload`` is advertised
as an empty object without a ``target``.  For that specific malformed action
descriptor, this strategy derives the conventional action URI from the
advertised Manager resource rather than treating an unadvertised action as
available.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.common import Collection, Link
from ...models.managers import Manager
from ...models.task import Task
from .base import BaseLogCollectStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

_DUMP_ACTION = "#Manager.Dump"
_DOWNLOAD_ACTION = "#Manager.GeneralDownload"
_SDS_PATH = "/mnt/sdmmc0p1/sds/bmc/dump.tar.gz"


class H3cLogCollectStrategy(BaseLogCollectStrategy):
    """Collect and download H3C SDS bundles through Manager OEM actions."""

    def find_existing_task(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        manager_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Always create a fresh SDS bundle at H3C's fixed artifact path."""
        return None

    def discover_collect_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        log_id: Optional[str],
    ) -> Optional[str]:
        """Return the Manager-level ``Manager.Dump`` action target."""
        manager = self._manager_for_log_services(client, log_services_odata_id)
        advertised, target = self._manager_oem_action(manager, _DUMP_ACTION)
        return target if advertised else None

    def build_collect_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build H3C's request for generating an SDS archive on the BMC."""
        body: Dict[str, Any] = {
            "Type": "URI",
            "Content": _SDS_PATH,
        }
        if diagnostic_data_type:
            body["LogType"] = diagnostic_data_type
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
        manager_id: Optional[str] = None,
    ) -> Task:
        """POST ``Manager.Dump`` and convert its task collection response."""
        from ...exceptions import RedfishValidationError

        manager = self._manager_for_log_services(client, log_services_odata_id)
        advertised, target = self._manager_oem_action(manager, _DUMP_ACTION)
        if not advertised or not target:
            raise RedfishValidationError(
                f"H3C Manager {manager.odata_id!r} does not expose "
                f"{_DUMP_ACTION} with an action target"
            )

        body = self.build_collect_body(diagnostic_data_type, oem_params)
        logger.info("H3C Manager.Dump POST %s body=%s", target, body)
        response = client._http_client.post(
            target, Collection[Link], raw_body=body
        )

        task_url = next(
            (
                member.odata_id
                for member in response.members or []
                if member.odata_id
            ),
            None,
        )
        if not task_url and response.odata_id and "/Tasks/" in response.odata_id:
            task_url = response.odata_id
        if not task_url:
            raise RedfishValidationError(
                "H3C Manager.Dump did not return a Redfish Task reference"
            )

        return Task.model_construct(
            id=task_url.rstrip("/").rsplit("/", 1)[-1],
            odata_id=task_url,
            _h3c_manager_id=self._manager_id(manager),
        )

    def wait_until_ready(
        self,
        client: "RedfishClient",
        task: Task,
        poll_interval: int = 5,
        timeout: int = 1800,
    ) -> Task:
        """Wait through TaskService while retaining the owning Manager id."""
        finished = super().wait_until_ready(
            client, task, poll_interval=poll_interval, timeout=timeout
        )
        manager_id = getattr(task, "_h3c_manager_id", None)
        if manager_id:
            finished = finished.model_copy(
                update={"_h3c_manager_id": manager_id}
            )
        return finished

    def download_artifact(
        self,
        client: "RedfishClient",
        task: Task,
        output_path: Optional[str] = None,
    ) -> "bytes | str":
        """POST ``Manager.GeneralDownload`` and save the returned archive."""
        from ...exceptions import RedfishValidationError

        manager_id = getattr(task, "_h3c_manager_id", None)
        manager = client.get_manager(manager_id)
        advertised, target = self._manager_oem_action(
            manager, _DOWNLOAD_ACTION
        )
        if not advertised:
            raise RedfishValidationError(
                f"H3C Manager {manager.odata_id!r} does not advertise "
                f"{_DOWNLOAD_ACTION}"
            )
        if not target and manager.odata_id:
            target = (
                f"{manager.odata_id.rstrip('/')}"
                "/Actions/Oem/Public/Manager.GeneralDownload"
            )
        if not target:
            raise RedfishValidationError(
                f"Could not resolve {_DOWNLOAD_ACTION} for H3C Manager"
            )

        body = {
            "TransferProtocol": "HTTPS",
            "Content": _SDS_PATH,
        }
        logger.info("H3C Manager.GeneralDownload POST %s", target)
        return client._http_client.download_via_post(
            target, output_path, raw_body=body
        )

    @staticmethod
    def _manager_for_log_services(
        client: "RedfishClient", log_services_odata_id: str
    ) -> Manager:
        """Resolve the Manager owning an advertised LogServices collection."""
        suffix = "/LogServices"
        manager_url = log_services_odata_id.rstrip("/")
        if manager_url.endswith(suffix):
            manager_url = manager_url[: -len(suffix)]
        manager_id = manager_url.rstrip("/").rsplit("/", 1)[-1]
        return client.get_manager(manager_id)

    @staticmethod
    def _manager_id(manager: Manager) -> Optional[str]:
        if manager.odata_id:
            return manager.odata_id.rstrip("/").rsplit("/", 1)[-1]
        return str(manager.id) if manager.id is not None else None

    @staticmethod
    def _manager_oem_action(
        manager: Manager, action_name: str
    ) -> tuple[bool, Optional[str]]:
        """Return whether an H3C OEM action is advertised and its target."""
        if manager.actions is None:
            return False, None
        actions = manager.actions.model_dump(by_alias=True, exclude_none=True)
        oem = actions.get("Oem")
        public = oem.get("Public") if isinstance(oem, dict) else None
        if not isinstance(public, dict) or action_name not in public:
            return False, None
        descriptor = public[action_name]
        if not isinstance(descriptor, dict):
            return True, None
        target = descriptor.get("target")
        return True, target if isinstance(target, str) and target else None
