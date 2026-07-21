"""
Task service models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from .common import Entity, Link, Status


class TaskService(Entity):
    """
    The Task service manages asynchronous tasks.
    Endpoint: /redfish/v1/TaskService
    """
    tasks: Optional[Link] = Field(None, alias="Tasks")
    completion_task_over_write_policy: Optional[str] = Field(
        None, alias="CompletionTaskOverWritePolicy"
    )
    date_time: Optional[str] = Field(None, alias="DateTime")
    life_cycle_event_on_task_state_change: Optional[bool] = Field(
        None, alias="LifeCycleEventOnTaskStateChange"
    )
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    status: Optional[Status] = Field(None, alias="Status")


class Message(Entity):
    """A message associated with a task."""
    message: Optional[str] = Field(None, alias="Message")
    message_args: Optional[List[str]] = Field(None, alias="MessageArgs")
    message_id: Optional[str] = Field(None, alias="MessageId")
    resolution: Optional[str] = Field(None, alias="Resolution")
    severity: Optional[str] = Field(None, alias="Severity")


class Task(Entity):
    """
    Represents an asynchronous task.
    Endpoint: /redfish/v1/TaskService/Tasks/{taskId}

    Long-running operations (e.g., firmware update) return a Task resource.
    """
    end_time: Optional[str] = Field(None, alias="EndTime")
    messages: Optional[List[Message]] = Field(None, alias="Messages")
    percent_complete: Optional[int] = Field(None, alias="PercentComplete")
    start_time: Optional[str] = Field(None, alias="StartTime")
    task_monitor: Optional[str] = Field(None, alias="TaskMonitor")
    task_state: Optional[str] = Field(None, alias="TaskState")
    task_status: Optional[str] = Field(None, alias="TaskStatus")
    status: Optional[Status] = Field(None, alias="Status")
