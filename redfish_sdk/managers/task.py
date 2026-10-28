"""
Task service manager — manages asynchronous tasks.

"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, List

from ..exceptions import RedfishNotFoundError
from ..models.task import Task
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


class TaskServiceManager:
    """
    Manages Redfish Task resources.


    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def tasks(self) -> List[Task]:
        """
        Get the list of all tasks.
        """
        task_service = self._client._get_task_service()
        return self._client._get_collection(task_service.tasks.odata_id, Task)

    def get(self, task_id: str) -> Task:
        """
        Get a specific task by ID.

        Args:
            task_id: Advertised Task Id or ``@odata.id``.

        Returns:
            Task resource
        """
        if task_id.startswith("/"):
            return self._http.get(task_id, Task)
        try:
            return select_member(self.tasks(), task_id)
        except RedfishNotFoundError:
            # Compatibility fallback for BMCs whose running tasks are
            # retrievable but temporarily omitted from the Tasks collection.
            task_service = self._client._get_task_service()
            if not task_service.tasks or not task_service.tasks.odata_id:
                raise
            path = f"{task_service.tasks.odata_id}/{task_id}"
            logger.debug(
                "Task %s is not advertised in the collection; trying %s",
                task_id,
                path,
            )
            return self._http.get(path, Task)

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: int = 5,
        timeout: int = 600,
    ) -> Task:
        """
        Poll a task until it completes or times out.

        Useful for monitoring long-running firmware update tasks.

        Args:
            task_id: Task ID to monitor
            poll_interval: Seconds between polls (default 5)
            timeout: Maximum wait time in seconds (default 600)

        Returns:
            Completed Task resource

        Raises:
            TimeoutError: If task does not complete within timeout
        """
        elapsed = 0
        while elapsed < timeout:
            task = self.get(task_id)
            state = task.task_state or ""
            logger.info(
                "Task %s: state=%s, percent=%s%%",
                task_id, state, task.percent_complete
            )

            if state in ("Completed", "Exception", "Killed", "Cancelled"):
                return task

            time.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"Task {task_id} did not complete within {timeout} seconds"
        )
