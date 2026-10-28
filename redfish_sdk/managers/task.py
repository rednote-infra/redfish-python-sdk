"""
Task service manager — manages asynchronous tasks.

"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, List, Optional

from ..exceptions import (
    RedfishAsyncOperationError,
    RedfishAuthError,
    RedfishConnectionError,
    RedfishNotFoundError,
    RedfishTimeoutError,
    RedfishValidationError,
)
from ..models.common import RedfishResponse
from ..models.task import AsyncOperationResult, Task, TaskRecoveryPolicy
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)

_TERMINAL_STATES = frozenset({"Completed", "Exception", "Killed", "Cancelled"})
_FAILED_STATES = frozenset({"Exception", "Killed", "Cancelled"})


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
        *,
        recovery_policy: Optional[TaskRecoveryPolicy] = None,
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
        policy = recovery_policy or TaskRecoveryPolicy()
        deadline = time.monotonic() + timeout
        connection_attempts = 0
        auth_attempts = 0
        while time.monotonic() < deadline:
            try:
                task = self.get(task_id)
            except (RedfishConnectionError, RedfishTimeoutError) as exc:
                if connection_attempts >= policy.max_connection_attempts:
                    raise RedfishAsyncOperationError(
                        0,
                        f"Unable to reconnect while monitoring task {task_id}",
                        task_uri=task_id if task_id.startswith("/") else "",
                        recovery_attempts=connection_attempts,
                    ) from exc
                connection_attempts += 1
                self._sleep(policy.recovery_interval, deadline, task_id)
                continue
            except RedfishAuthError as exc:
                if auth_attempts >= policy.max_auth_attempts:
                    raise RedfishAsyncOperationError(
                        exc.status_code,
                        f"Authentication expired while monitoring task {task_id}; "
                        "bounded reauthentication attempts were exhausted",
                        task_uri=task_id if task_id.startswith("/") else "",
                        recovery_attempts=auth_attempts,
                    ) from exc
                auth_attempts += 1
                self._http.reset_basic_auth()
                continue

            connection_attempts = 0
            state = task.task_state or ""
            logger.info(
                "Task %s: state=%s, percent=%s%%",
                task_id, state, task.percent_complete
            )

            if state in _TERMINAL_STATES:
                return task

            delay = self._offline_delay(task) or float(poll_interval)
            self._sleep(delay, deadline, task_id)

        raise TimeoutError(
            f"Task {task_id} did not complete within {timeout} seconds"
        )

    def wait_for_operation(
        self,
        operation: RedfishResponse,
        poll_interval: int = 5,
        timeout: int = 600,
        *,
        recovery_policy: Optional[TaskRecoveryPolicy] = None,
    ) -> AsyncOperationResult:
        """Wait on an opaque task monitor without replaying its mutation.

        The initial response must retain the ``202`` status and ``Location``
        header. ``@odata.id`` is tracked separately as the Task resource URI
        and is only used to verify terminal state if a monitor expires.
        """
        monitor_uri = operation.task_monitor
        if operation.http_status != 202 or not monitor_uri:
            raise RedfishValidationError(
                "The response does not describe an asynchronous operation: "
                "HTTP 202 and a task-monitor Location are required"
            )

        task_uri = operation.task_uri or operation.odata_id
        task_resource_location = self._is_task_resource_uri(
            monitor_uri, task_uri
        )
        if task_resource_location:
            task_uri = task_uri or monitor_uri
        policy = recovery_policy or TaskRecoveryPolicy()
        deadline = time.monotonic() + timeout
        connection_attempts = 0
        auth_attempts = 0
        last_task: Optional[Task] = None

        initial_delay = self._retry_after_seconds(operation.retry_after)
        if initial_delay is not None:
            self._sleep(initial_delay, deadline, monitor_uri)

        while time.monotonic() < deadline:
            try:
                response = self._http._request("GET", monitor_uri)
            except (RedfishConnectionError, RedfishTimeoutError) as exc:
                if connection_attempts >= policy.max_connection_attempts:
                    raise RedfishAsyncOperationError(
                        0,
                        "Unable to reconnect while monitoring asynchronous operation",
                        task_monitor_uri=monitor_uri,
                        task_uri=task_uri or "",
                        recovery_attempts=connection_attempts,
                    ) from exc
                connection_attempts += 1
                self._sleep(policy.recovery_interval, deadline, monitor_uri)
                continue

            if response.status_code in (401, 403):
                if auth_attempts >= policy.max_auth_attempts:
                    raise RedfishAsyncOperationError(
                        response.status_code,
                        "Authentication expired while monitoring asynchronous "
                        "operation; bounded reauthentication attempts were exhausted",
                        response.text,
                        task_monitor_uri=monitor_uri,
                        task_uri=task_uri or "",
                        final_response=response,
                        recovery_attempts=auth_attempts,
                    )
                auth_attempts += 1
                self._http.reset_basic_auth()
                continue

            connection_attempts = 0
            if task_resource_location and response.status_code == 200:
                task = self._http._parse(response, Task)
                last_task = task
                state = task.task_state or ""
                if state == "Completed":
                    return AsyncOperationResult(
                        initial_http_status=operation.http_status,
                        task_monitor_uri=monitor_uri,
                        task_uri=task_uri,
                        initial_retry_after=operation.retry_after,
                        final_response=response,
                        task=task,
                    )
                if state in _FAILED_STATES:
                    raise RedfishAsyncOperationError(
                        response.status_code,
                        f"Asynchronous task entered failure state {state}",
                        response.text,
                        task_monitor_uri=monitor_uri,
                        task_uri=task_uri or "",
                        final_response=response,
                    )
                delay = self._retry_after_seconds(
                    response.headers.get("Retry-After")
                )
                if delay is None:
                    delay = self._offline_delay(task)
                self._sleep(
                    delay if delay is not None else float(poll_interval),
                    deadline,
                    monitor_uri,
                )
                continue

            if response.status_code == 202:
                task = self._task_from_response(response)
                if task is not None:
                    last_task = task
                    task_uri = task_uri or task.odata_id
                delay = self._retry_after_seconds(response.headers.get("Retry-After"))
                if delay is None and task is not None:
                    delay = self._offline_delay(task)
                self._sleep(
                    delay if delay is not None else float(poll_interval),
                    deadline,
                    monitor_uri,
                )
                continue

            if response.status_code in (404, 410):
                terminal_task = self._verify_missing_monitor(
                    task_uri, monitor_uri, response
                )
                return AsyncOperationResult(
                    initial_http_status=operation.http_status,
                    task_monitor_uri=monitor_uri,
                    task_uri=task_uri,
                    initial_retry_after=operation.retry_after,
                    final_response=response,
                    task=terminal_task,
                    monitor_missing=True,
                )

            if not 200 <= response.status_code < 300:
                raise RedfishAsyncOperationError(
                    response.status_code,
                    "Asynchronous operation completed with an HTTP error",
                    response.text,
                    task_monitor_uri=monitor_uri,
                    task_uri=task_uri or "",
                    final_response=response,
                )

            return AsyncOperationResult(
                initial_http_status=operation.http_status,
                task_monitor_uri=monitor_uri,
                task_uri=task_uri,
                initial_retry_after=operation.retry_after,
                final_response=response,
                task=last_task,
            )

        raise TimeoutError(
            f"Asynchronous operation at {monitor_uri} did not complete "
            f"within {timeout} seconds"
        )

    def _verify_missing_monitor(
        self,
        task_uri: Optional[str],
        monitor_uri: str,
        monitor_response,
    ) -> Task:
        if not task_uri:
            raise RedfishAsyncOperationError(
                monitor_response.status_code,
                "Task monitor disappeared before terminal task state could be verified",
                monitor_response.text,
                task_monitor_uri=monitor_uri,
                final_response=monitor_response,
            )

        response = self._http._request("GET", task_uri)
        if response.status_code != 200:
            raise RedfishAsyncOperationError(
                response.status_code,
                "Task monitor disappeared and the Task resource could not verify completion",
                response.text,
                task_monitor_uri=monitor_uri,
                task_uri=task_uri,
                final_response=monitor_response,
            )
        task = self._http._parse(response, Task)
        state = task.task_state or ""
        if state not in _TERMINAL_STATES:
            raise RedfishAsyncOperationError(
                monitor_response.status_code,
                "Task monitor disappeared before terminal task state could be verified",
                monitor_response.text,
                task_monitor_uri=monitor_uri,
                task_uri=task_uri,
                final_response=monitor_response,
            )
        if state in _FAILED_STATES:
            raise RedfishAsyncOperationError(
                monitor_response.status_code,
                f"Task monitor disappeared after task entered failure state {state}",
                monitor_response.text,
                task_monitor_uri=monitor_uri,
                task_uri=task_uri,
                final_response=monitor_response,
            )
        return task

    def _task_from_response(self, response) -> Optional[Task]:
        if not response.text.strip():
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict) or not any(
            key in body for key in ("TaskState", "TaskStatus", "@odata.id")
        ):
            return None
        return Task.model_validate(body)

    @staticmethod
    def _is_task_resource_uri(
        location: str, task_uri: Optional[str]
    ) -> bool:
        if task_uri and location.rstrip("/") == task_uri.rstrip("/"):
            return True
        path = location.split("?", 1)[0].rstrip("/")
        return "/TaskService/Tasks/" in path and "/TaskMonitors/" not in path

    @staticmethod
    def _offline_delay(task: Task) -> Optional[float]:
        for message in task.messages or []:
            if not (message.message_id or "").endswith(
                "ManagerGoingOfflineTemporarily"
            ):
                continue
            args = message.message_args or []
            candidates = args[1:] if len(args) > 1 else args
            for value in candidates:
                try:
                    return max(float(value), 0.0)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            pass
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(
                (retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0
            )
        except (TypeError, ValueError, OverflowError):
            logger.warning("Ignoring invalid Retry-After value %r", value)
            return None

    @staticmethod
    def _sleep(delay: float, deadline: float, resource: str) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or delay > remaining:
            raise TimeoutError(
                f"Timed out while waiting to poll asynchronous resource {resource}"
            )
        time.sleep(delay)
