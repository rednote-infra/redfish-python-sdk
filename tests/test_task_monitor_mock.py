"""Asynchronous Task and task-monitor recovery behavior."""

import json
from unittest.mock import Mock

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import (
    RedfishAsyncOperationError,
    RedfishConnectionError,
)
from redfish_sdk.models.common import RedfishResponse
from redfish_sdk.models.task import Task, TaskRecoveryPolicy
from redfish_sdk.models.update import FirmwareUpdateResponse


def response(status, body=None, headers=None):
    result = requests.Response()
    result.request = requests.Request(
        "GET", "https://mock-bmc/redfish/v1/TaskService/TaskMonitors/7"
    ).prepare()
    result.status_code = status
    result._content = json.dumps(body).encode() if body is not None else b""
    result.headers.update(headers or {})
    return result


@pytest.fixture
def client():
    value = RedfishClient(host="mock-bmc", username="user", password="password")
    yield value
    value.close()


def operation(**overrides):
    values = {
        "@odata.id": "/redfish/v1/TaskService/Tasks/7",
        "Id": "7",
        "TaskState": "Running",
        "TaskMonitor": "/redfish/v1/TaskService/TaskMonitors/7",
        "HttpStatus": 202,
        "RetryAfter": "2",
    }
    values.update(overrides)
    return FirmwareUpdateResponse.model_validate(values)


def test_wait_for_operation_recovers_without_replaying_mutation(client, monkeypatch):
    monitor = "/redfish/v1/TaskService/TaskMonitors/7"
    scripted = iter([
        response(
            202,
            {
                "@odata.id": "/redfish/v1/TaskService/Tasks/7",
                "Id": "7",
                "TaskState": "Running",
                "Messages": [{
                    "MessageId": "Manager.1.0.ManagerGoingOfflineTemporarily",
                    "MessageArgs": ["BMC", "30"],
                }],
            },
            {"Retry-After": "30"},
        ),
        RedfishConnectionError("mock-bmc", ConnectionError("restarting")),
        response(401, {"error": {"code": "Base.1.0.NoValidSession"}}),
        response(200, {"result": "updated"}, {"ETag": '"final"'}),
    ])
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path))
        item = next(scripted)
        if isinstance(item, Exception):
            raise item
        return item

    sleeps = []
    reset_auth = Mock(wraps=client._http_client.reset_basic_auth)
    monkeypatch.setattr(client._http_client, "_request", request)
    monkeypatch.setattr(client._http_client, "reset_basic_auth", reset_auth)
    monkeypatch.setattr("redfish_sdk.managers.task.time.sleep", sleeps.append)

    result = client.wait_for_operation(
        operation(),
        timeout=120,
        recovery_policy=TaskRecoveryPolicy(
            max_connection_attempts=2,
            max_auth_attempts=1,
            recovery_interval=3,
        ),
    )

    assert calls == [("GET", monitor)] * 4
    assert sleeps == [2.0, 30.0, 3.0]
    reset_auth.assert_called_once_with()
    assert result.initial_http_status == 202
    assert result.task_monitor_uri == monitor
    assert result.task_uri == "/redfish/v1/TaskService/Tasks/7"
    assert result.initial_retry_after == "2"
    assert result.final_response.status_code == 200
    assert result.final_response.json() == {"result": "updated"}
    assert result.task is not None
    assert result.task.task_state == "Running"
    assert result.monitor_missing is False


def test_wait_for_operation_does_not_treat_unverified_missing_monitor_as_success(
    client, monkeypatch
):
    monkeypatch.setattr(
        client._http_client,
        "_request",
        lambda *args, **kwargs: response(404, {"error": {"code": "NotFound"}}),
    )

    with pytest.raises(
        RedfishAsyncOperationError,
        match="Task monitor disappeared before terminal task state could be verified",
    ) as error:
        client.wait_for_operation(operation(**{"@odata.id": None}), timeout=30)

    assert error.value.status_code == 404
    assert error.value.task_monitor_uri.endswith("/TaskMonitors/7")


def test_wait_for_operation_uses_task_to_verify_gone_monitor(client, monkeypatch):
    task_uri = "/redfish/v1/TaskService/Tasks/7"
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path))
        if path.endswith("TaskMonitors/7"):
            return response(410, {"error": {"code": "Gone"}})
        return response(200, {
            "@odata.id": task_uri,
            "Id": "7",
            "TaskState": "Completed",
            "TaskStatus": "OK",
        })

    monkeypatch.setattr(client._http_client, "_request", request)

    result = client.wait_for_operation(operation(), timeout=30)

    assert calls == [
        ("GET", "/redfish/v1/TaskService/TaskMonitors/7"),
        ("GET", task_uri),
    ]
    assert result.monitor_missing is True
    assert result.final_response.status_code == 410
    assert result.task.task_state == "Completed"


def test_wait_for_operation_reports_terminal_failure(client, monkeypatch):
    failure = response(
        400,
        {
            "error": {
                "code": "Update.1.0.ApplyFailed",
                "message": "Firmware verification failed",
            }
        },
    )
    monkeypatch.setattr(
        client._http_client, "_request", lambda *args, **kwargs: failure
    )

    with pytest.raises(RedfishAsyncOperationError) as error:
        client.wait_for_operation(operation(), timeout=30)

    assert error.value.status_code == 400
    assert "Firmware verification failed" in error.value.body
    assert error.value.final_response is failure


def test_wait_for_task_keeps_compatible_result_and_uses_monotonic_deadline(
    client, monkeypatch
):
    tasks = iter([
        Task.model_validate({
            "Id": "7",
            "TaskState": "Running",
            "Messages": [{
                "MessageId": "Manager.1.0.ManagerGoingOfflineTemporarily",
                "MessageArgs": ["BMC", "9"],
            }],
        }),
        Task.model_validate({
            "Id": "7", "TaskState": "Completed", "TaskStatus": "OK"
        }),
    ])
    monotonic = iter([100.0, 100.0, 100.0, 109.0])
    sleeps = []
    monkeypatch.setattr(client._tasks, "get", lambda task_id: next(tasks))
    monkeypatch.setattr(
        "redfish_sdk.managers.task.time.monotonic", lambda: next(monotonic)
    )
    monkeypatch.setattr("redfish_sdk.managers.task.time.sleep", sleeps.append)

    result = client.wait_for_task("7", poll_interval=2, timeout=30)

    assert result.task_state == "Completed"
    assert sleeps == [9.0]


def test_wait_for_operation_has_bounded_connection_recovery(client, monkeypatch):
    monkeypatch.setattr(
        client._http_client,
        "_request",
        Mock(side_effect=RedfishConnectionError("mock-bmc", ConnectionError())),
    )
    monkeypatch.setattr("redfish_sdk.managers.task.time.sleep", lambda value: None)

    with pytest.raises(
        RedfishAsyncOperationError,
        match="Unable to reconnect while monitoring asynchronous operation",
    ) as error:
        client.wait_for_operation(
            operation(),
            timeout=30,
            recovery_policy=TaskRecoveryPolicy(
                max_connection_attempts=1,
                recovery_interval=0,
            ),
        )

    assert error.value.recovery_attempts == 1


def test_generic_mutation_response_retains_async_monitor_metadata(client, monkeypatch):
    initial = response(
        202,
        {"@odata.id": "/redfish/v1/TaskService/Tasks/8", "TaskState": "Running"},
        {
            "Location": "/redfish/v1/TaskService/TaskMonitors/8",
            "Retry-After": "12",
        },
    )
    monkeypatch.setattr(client._http_client, "_request", lambda *args, **kwargs: initial)

    result = client._http_client.post(
        "/redfish/v1/Actions/Example.Start", RedfishResponse, raw_body={}
    )

    assert result.http_status == 202
    assert result.task_monitor == "/redfish/v1/TaskService/TaskMonitors/8"
    assert result.task_uri == "/redfish/v1/TaskService/Tasks/8"
    assert result.retry_after == "12"


def test_task_response_retains_artifact_header_metadata(client, monkeypatch):
    initial = response(
        202,
        {"@odata.id": "/redfish/v1/TaskService/Tasks/8", "TaskState": "Running"},
        {
            "Location": "/redfish/v1/TaskService/TaskMonitors/8",
            "Content-Location": "/redfish/v1/download/diagnostic.tar.gz",
            "Retry-After": "12",
        },
    )
    monkeypatch.setattr(client._http_client, "_request", lambda *args, **kwargs: initial)

    result = client._http_client.post(
        "/redfish/v1/Actions/LogService.CollectDiagnosticData", Task, raw_body={}
    )

    assert result.initial_http_status == 202
    assert result.task_monitor == "/redfish/v1/TaskService/TaskMonitors/8"
    assert result.initial_location == "/redfish/v1/TaskService/TaskMonitors/8"
    assert result.initial_content_location == "/redfish/v1/download/diagnostic.tar.gz"
    assert result.initial_retry_after == "12"


def test_wait_for_operation_supports_legacy_task_uri_location(client, monkeypatch):
    task_uri = "/redfish/v1/TaskService/Tasks/9"
    scripted = iter([
        response(200, {
            "@odata.id": task_uri,
            "Id": "9",
            "TaskState": "Running",
            "PercentComplete": 50,
        }, {"Retry-After": "4"}),
        response(200, {
            "@odata.id": task_uri,
            "Id": "9",
            "TaskState": "Completed",
            "TaskStatus": "OK",
            "PercentComplete": 100,
        }),
    ])
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path))
        return next(scripted)

    sleeps = []
    monkeypatch.setattr(client._http_client, "_request", request)
    monkeypatch.setattr("redfish_sdk.managers.task.time.sleep", sleeps.append)

    result = client.wait_for_operation(
        operation(
            **{
                "@odata.id": task_uri,
                "TaskMonitor": task_uri,
                "RetryAfter": None,
            }
        ),
        timeout=30,
    )

    assert calls == [("GET", task_uri), ("GET", task_uri)]
    assert sleeps == [4.0]
    assert result.task.task_state == "Completed"
    assert result.final_response.status_code == 200
