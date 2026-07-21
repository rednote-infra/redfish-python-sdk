"""
Log service models.

"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from .common import Entity, Link, Status


class Log(Entity):
    """
    Represents a log service on a system or manager.
    Endpoint: /redfish/v1/Systems/{id}/LogServices/{logId}
              /redfish/v1/Managers/{id}/LogServices/{logId}

    """
    date_time: Optional[str] = Field(None, alias="DateTime")
    date_time_local_offset: Optional[str] = Field(None, alias="DateTimeLocalOffset")
    entries: Optional[Link] = Field(None, alias="Entries")
    max_number_of_records: Optional[int] = Field(None, alias="MaxNumberOfRecords")
    overwrite_policy: Optional[str] = Field(None, alias="OverWritePolicy")
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    status: Optional[Status] = Field(None, alias="Status")
    # Redfish Actions block (e.g. #LogService.ClearLog).
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")


class LogEntry(Entity):
    """
    A single log entry within a log service.
    Endpoint: /redfish/v1/Systems/{id}/LogServices/{logId}/Entries/{entryId}

    """
    created: Optional[str] = Field(None, alias="Created")
    entry_code: Optional[str] = Field(None, alias="EntryCode")
    entry_type: Optional[str] = Field(None, alias="EntryType")
    message: Optional[str] = Field(None, alias="Message")
    message_args: Optional[list] = Field(None, alias="MessageArgs")
    message_id: Optional[str] = Field(None, alias="MessageId")
    oem_log_entry_code: Optional[str] = Field(None, alias="OemLogEntryCode")
    oem_record_format: Optional[str] = Field(None, alias="OemRecordFormat")
    sensor_number: Optional[int] = Field(None, alias="SensorNumber")
    sensor_type: Optional[str] = Field(None, alias="SensorType")
    severity: Optional[str] = Field(None, alias="Severity")
    status: Optional[Status] = Field(None, alias="Status")
    # DMTF v1.4 optional fields commonly needed for
    # compliance checks (e.g. bmc_autotest managers_004*_*_log_check.py).
    # ``odata_id`` / ``odata_type`` are already inherited from Entity.
    event_timestamp: Optional[str] = Field(None, alias="EventTimestamp")
    diagnostic_data_size_bytes: Optional[int] = Field(
        None, alias="DiagnosticDataSizeBytes"
    )
