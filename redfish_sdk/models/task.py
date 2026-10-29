"""
Task service models.

"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    message_severity: Optional[str] = Field(None, alias="MessageSeverity")
    resolution: Optional[str] = Field(None, alias="Resolution")
    severity: Optional[str] = Field(None, alias="Severity")
    vendor_code: Optional[str] = Field(None, alias="VendorCode")


class TaskPayload(BaseModel):
    """Optional ``Task.Payload`` block — describes the operation the task
    was created from (target URL, HTTP verb, request headers/body)."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    http_operation: Optional[str] = Field(None, alias="HttpOperation")
    target_uri: Optional[str] = Field(None, alias="TargetUri")
    json_body: Optional[str] = Field(None, alias="JsonBody")
    http_headers: Optional[List[str]] = Field(None, alias="HttpHeaders")


class TaskLinks(BaseModel):
    """Task's ``Links`` sub-object — some BMCs use ``CreatedResources`` here
    to point at the produced artifact (e.g. a LogEntry)."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    created_resources: Optional[List[Link]] = Field(
        None, alias="CreatedResources"
    )


class Task(Entity):
    """
    Represents an asynchronous task.
    Endpoint: /redfish/v1/TaskService/Tasks/{taskId}

    Long-running operations (e.g., firmware update, diagnostic log
    collection) return a Task resource.
    """
    end_time: Optional[str] = Field(None, alias="EndTime")
    messages: Optional[List[Message]] = Field(None, alias="Messages")
    percent_complete: Optional[int] = Field(None, alias="PercentComplete")
    start_time: Optional[str] = Field(None, alias="StartTime")
    task_monitor: Optional[str] = Field(None, alias="TaskMonitor")
    task_state: Optional[str] = Field(None, alias="TaskState")
    task_status: Optional[str] = Field(None, alias="TaskStatus")
    status: Optional[Status] = Field(None, alias="Status")
    #: Optional payload describing the underlying request (target URI etc.)
    #: — used by log-collection heuristics to identify collect tasks.
    payload: Optional[TaskPayload] = Field(None, alias="Payload")
    #: Task ``Links`` — carries ``CreatedResources`` on some BMCs.
    links: Optional[TaskLinks] = Field(None, alias="Links")
    #: Some BMCs inline the produced artifact URI directly on the task body
    #: (non-standard but observed in the wild).
    additional_data_uri: Optional[str] = Field(None, alias="AdditionalDataURI")
    # Transport metadata retained from the response that created this task.
    # These fields are SDK context, not Redfish payload properties, so they
    # are excluded from model serialisation.
    initial_http_status: Optional[int] = Field(None, exclude=True)
    initial_location: Optional[str] = Field(None, exclude=True)
    initial_content_location: Optional[str] = Field(None, exclude=True)
    initial_retry_after: Optional[str] = Field(None, exclude=True)
    source_log_service_uri: Optional[str] = Field(None, exclude=True)
    #: Vendor-specific ``Oem`` block (opaque; strategies read it as needed).
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")

    @field_validator("messages", mode="before")
    @classmethod
    def _normalise_messages(cls, value: Any) -> Any:
        """
        Accept a single ``Messages`` dict as if it were a one-element list.

        The DMTF schema declares ``Task.Messages`` as an array, but some BMC
        firmwares (observed on smoothcompute 6415 X2) put a single Message
        object there. Wrap it so pydantic validation succeeds instead of
        failing an otherwise-usable Task response.
        """
        if isinstance(value, dict):
            return [value]
        return value


@dataclass(frozen=True)
class TaskRecoveryPolicy:
    """Bounded recovery settings for asynchronous operation polling.

    Recovery only retries status ``GET`` requests. The SDK never replays the
    original mutation that created the asynchronous operation.
    """

    max_connection_attempts: int = 3
    max_auth_attempts: int = 1
    recovery_interval: float = 5.0

    def __post_init__(self) -> None:
        if self.max_connection_attempts < 0:
            raise ValueError("max_connection_attempts must be non-negative")
        if self.max_auth_attempts < 0:
            raise ValueError("max_auth_attempts must be non-negative")
        if self.recovery_interval < 0:
            raise ValueError("recovery_interval must be non-negative")


@dataclass(frozen=True)
class AsyncOperationResult:
    """Completed asynchronous operation and its original HTTP response."""

    initial_http_status: int
    task_monitor_uri: str
    task_uri: Optional[str]
    initial_retry_after: Optional[str]
    final_response: requests.Response
    task: Optional[Task] = None
    monitor_missing: bool = False
