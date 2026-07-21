"""
Mock tests for log_entries dynamic discovery + per-entry GET.

Covers:
  - LogEntry parses DMTF metadata fields (odata_type, EventTimestamp,
    DiagnosticDataSizeBytes).
  - log_entries reads ``Log.entries.odata_id`` dynamically (no path
    concatenation).
  - log_id is Optional; auto-selected when there is exactly one
    LogService, raises RedfishValidationError when multiple exist, and
    raises 404 when the collection is empty.
  - log_service is sourced by listing the LogServices collection and
    matching ``Log.id`` rather than building a URL.
  - Missing-LogServices-link guard: log_services / log_service /
    log_entries all raise a clear 404 when System.log_services is None
    (or the link's odata_id is empty).
  - Manager-side has identical behaviour.

History (design notes):
    An earlier prototype used ``?$expand=.($levels=1)`` to inline the
    Entries collection in one round trip. Real-world testing against
    multiple BMCs showed that some servers silently return an empty
    collection (``Members@odata.count: 0``) when given that query while
    entries actually exist — see the commit message of this change for
    the captured curl output. There is no wire-level signal that
    distinguishes "BMC genuinely has no entries" from "BMC broke expand",
    so the SDK no longer attempts ``$expand`` and always falls back to
    per-entry GET via ``_get_collection``. Callers needing throughput
    can parallelise externally.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import pytest

from redfish_sdk import (
    Log,
    LogEntry,
    RedfishClient,
    RedfishException,
    RedfishValidationError,
)
from redfish_sdk.models.common import Link
from redfish_sdk.models.systems import System

MOCK_HOST = os.environ.get("BMC_IP", "mock-bmc-host")
MOCK_USER = os.environ.get("BMC_USER", "mock-user")
MOCK_PASSWORD = os.environ.get("BMC_PASSWORD", "mock-password")


def _make_client() -> RedfishClient:
    return RedfishClient(host=MOCK_HOST, username=MOCK_USER, password=MOCK_PASSWORD)


def _system_with_log_services(odata_id: str = "/redfish/v1/Systems/1/LogServices") -> System:
    return System.model_construct(
        id="1",
        odata_id="/redfish/v1/Systems/1",
        log_services=Link(**{"@odata.id": odata_id}),
    )


# ---------------------------------------------------------------------------
# LogEntry model parsing
# ---------------------------------------------------------------------------


class TestLogEntryModelFields:
    def test_parses_dmtf_optional_fields(self):
        raw = {
            "@odata.id": "/redfish/v1/Systems/1/LogServices/Sel/Entries/1",
            "@odata.type": "#LogEntry.v1_4_3.LogEntry",
            "Id": "1",
            "Name": "Log Entry 1",
            "EntryType": "SEL",
            "Severity": "OK",
            "Created": "2026-06-15T10:00:00Z",
            "EventTimestamp": "2026-06-15T10:00:00Z",
            "DiagnosticDataSizeBytes": 256,
        }
        entry = LogEntry(**raw)
        assert entry.odata_id.endswith("/Entries/1")
        assert entry.odata_type == "#LogEntry.v1_4_3.LogEntry"
        assert entry.event_timestamp == "2026-06-15T10:00:00Z"
        assert entry.diagnostic_data_size_bytes == 256
        # Existing fields still work.
        assert entry.entry_type == "SEL"


# ---------------------------------------------------------------------------
# log_entries — dynamic discovery + per-entry GET
# ---------------------------------------------------------------------------


class TestLogEntriesDynamicDiscovery:
    """The Entries collection URL must come from ``Log.entries.odata_id``,
    NOT from a hard-coded ``f"{log_services}/{log_id}/Entries"``.
    """

    def test_uses_custom_entries_link(self, monkeypatch):
        client = _make_client()
        system = _system_with_log_services()
        monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)

        # Both the per-service path and the entries link are vendor-specific
        # (NOT the default /Sel/Entries pattern). Catches naive concatenation.
        custom_service_id = "/redfish/v1/Systems/1/LogServices/SystemEventLog"
        custom_entries = f"{custom_service_id}/LogEntryCollection"
        sel = Log.model_construct(
            id="Sel",
            odata_id=custom_service_id,
            entries=Link(**{"@odata.id": custom_entries}),
        )

        collection_calls: List[Any] = []
        entries = [
            LogEntry.model_construct(id="1", odata_id=f"{custom_entries}/1"),
            LogEntry.model_construct(id="2", odata_id=f"{custom_entries}/2"),
        ]

        def fake_get_collection(odata_id, model_class):
            collection_calls.append((odata_id, model_class))
            if model_class is Log:
                return [sel]
            return entries

        monkeypatch.setattr(client, "_get_collection", fake_get_collection)

        result = client.get_system_log_entries("Sel")
        assert result == entries
        # 2 _get_collection calls:
        #   1) resolve_log_service lists LogServices
        #   2) fetch_log_entries lists the Entries collection via the
        #      VENDOR-SPECIFIC link, never touching '/Entries' nor '/Sel'
        assert collection_calls == [
            ("/redfish/v1/Systems/1/LogServices", Log),
            (custom_entries, LogEntry),
        ]
        # Sanity: never built a URL by concatenation.
        for path, _ in collection_calls:
            assert "/Sel/Entries" not in path
        client.close()

    def test_log_with_no_entries_link_returns_empty(self, monkeypatch):
        """A LogService that genuinely omits ``Entries`` -> ``[]`` (no crash)."""
        client = _make_client()
        system = _system_with_log_services()
        monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)

        sel = Log.model_construct(
            id="Sel",
            odata_id="/redfish/v1/Systems/1/LogServices/Sel",
            entries=None,
        )

        def fake_get_collection(odata_id, model_class):
            if model_class is Log:
                return [sel]
            raise AssertionError("must not list LogEntry collection")

        monkeypatch.setattr(client, "_get_collection", fake_get_collection)

        assert client.get_system_log_entries("Sel") == []
        client.close()


# ---------------------------------------------------------------------------
# Missing LogServices link guard
# ---------------------------------------------------------------------------


class TestMissingLogServicesLink:
    """When a BMC really omits the optional LogServices sub-resource the
    SDK must raise a clear 404 instead of crashing with AttributeError on
    ``None.odata_id``. The Optional[Link] typing of
    System/Manager.log_services exists precisely so this scenario is
    representable.
    """

    def _system_without_log_services(self) -> System:
        # Note: no ``log_services`` keyword — field defaults to None per model.
        return System.model_construct(id="1", odata_id="/redfish/v1/Systems/1")

    def test_system_log_entries_raises_404(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            client._systems, "get",
            lambda system_id=None: self._system_without_log_services(),
        )
        with pytest.raises(RedfishException, match="LogServices"):
            client.get_system_log_entries()
        client.close()

    def test_system_log_service_raises_404(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            client._systems, "get",
            lambda system_id=None: self._system_without_log_services(),
        )
        with pytest.raises(RedfishException, match="LogServices"):
            client.get_system_log_service("Sel")
        client.close()

    def test_system_log_services_raises_404(self, monkeypatch):
        client = _make_client()
        monkeypatch.setattr(
            client._systems, "get",
            lambda system_id=None: self._system_without_log_services(),
        )
        with pytest.raises(RedfishException, match="LogServices"):
            client.get_system_log_services()
        client.close()

    def test_link_present_but_odata_id_empty(self, monkeypatch):
        """Some BMCs return ``"LogServices": {}`` with no ``@odata.id``.
        Should be treated identically to "absent"."""
        client = _make_client()
        system = System.model_construct(
            id="1",
            odata_id="/redfish/v1/Systems/1",
            log_services=Link.model_construct(odata_id=None),
        )
        monkeypatch.setattr(
            client._systems, "get", lambda system_id=None: system
        )
        with pytest.raises(RedfishException, match="LogServices"):
            client.get_system_log_entries()
        client.close()


# ---------------------------------------------------------------------------
# log_id auto-selection / not-found
# ---------------------------------------------------------------------------


class TestLogIdSelection:
    def test_single_log_service_auto_selected(self, monkeypatch):
        client = _make_client()
        system = _system_with_log_services()
        monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)

        sel = Log.model_construct(
            id="Sel",
            odata_id="/redfish/v1/Systems/1/LogServices/Sel",
            entries=Link(**{"@odata.id": "/redfish/v1/Systems/1/LogServices/Sel/Entries"}),
        )
        entry = LogEntry.model_construct(
            id="1", odata_id="/redfish/v1/Systems/1/LogServices/Sel/Entries/1"
        )

        def fake_get_collection(odata_id, model_class):
            if model_class is Log:
                return [sel]
            return [entry]

        monkeypatch.setattr(client, "_get_collection", fake_get_collection)

        entries = client.get_system_log_entries()  # no log_id
        assert entries == [entry]
        client.close()

    def test_multiple_log_services_without_id_raises(self, monkeypatch):
        client = _make_client()
        system = _system_with_log_services()
        monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)

        sel = Log.model_construct(id="Sel", odata_id="/x/Sel")
        ops = Log.model_construct(id="OperateLog", odata_id="/x/OperateLog")
        monkeypatch.setattr(
            client, "_get_collection", lambda odata_id, mc: [sel, ops]
        )

        with pytest.raises(RedfishValidationError, match="Multiple log services"):
            client.get_system_log_entries()
        client.close()

    def test_no_log_services_raises_404(self, monkeypatch):
        client = _make_client()
        system = _system_with_log_services()
        monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)
        monkeypatch.setattr(client, "_get_collection", lambda *a, **k: [])
        with pytest.raises(RedfishException, match="No log services"):
            client.get_system_log_entries()
        client.close()


# ---------------------------------------------------------------------------
# log_service — dynamic discovery + unknown id
# ---------------------------------------------------------------------------


class TestLogServiceDynamicDiscovery:
    """log_service must obtain the per-service URL from the collection,
    NOT from string concatenation. Catches the regression where
    ``f"{log_services}/{log_id}"`` failed against vendors that publish a
    non-default child path.
    """

    def test_returns_member_with_custom_odata_id(self, monkeypatch):
        client = _make_client()
        system = _system_with_log_services()
        monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)

        # Note the per-service odata_id is NOT
        # /redfish/v1/Systems/1/LogServices/Sel — it's a vendor-specific
        # path. Concatenation would have produced the wrong URL.
        sel = Log.model_construct(
            id="Sel",
            odata_id="/redfish/v1/Systems/1/LogServices/SystemEventLog",
            actions={"#LogService.ClearLog": {"target": "/x/Actions/ClearLog"}},
        )
        operate = Log.model_construct(
            id="OperateLog",
            odata_id="/redfish/v1/Systems/1/LogServices/OperationLog",
        )
        monkeypatch.setattr(
            client, "_get_collection",
            lambda odata_id, mc: [sel, operate] if mc is Log else [],
        )
        # http_client.get must NOT be invoked: log_service is served
        # entirely from the collection lookup now.
        monkeypatch.setattr(
            client._http_client, "get",
            lambda path, mc: (_ for _ in ()).throw(
                AssertionError(f"unexpected http get {path}")
            ),
        )

        result = client.get_system_log_service("Sel")
        assert result is sel
        assert result.odata_id == "/redfish/v1/Systems/1/LogServices/SystemEventLog"
        client.close()

    def test_unknown_log_id_raises(self, monkeypatch):
        client = _make_client()
        system = _system_with_log_services()
        monkeypatch.setattr(client._systems, "get", lambda system_id=None: system)

        sel = Log.model_construct(id="Sel", odata_id="/x/Sel")
        monkeypatch.setattr(
            client, "_get_collection",
            lambda odata_id, mc: [sel] if mc is Log else [],
        )

        with pytest.raises(Exception) as ei:
            client.get_system_log_service("DoesNotExist")
        # RedfishNotFoundError; assert via available IDs message.
        assert "available=['Sel']" in str(ei.value)
        client.close()


# ---------------------------------------------------------------------------
# Manager-side parity
# ---------------------------------------------------------------------------


class TestManagerLogEntries:
    def test_manager_log_entries_uses_same_helper(self, monkeypatch):
        client = _make_client()
        from redfish_sdk.models.managers import Manager

        manager = Manager.model_construct(
            id="1",
            odata_id="/redfish/v1/Managers/1",
            log_services=Link(**{"@odata.id": "/redfish/v1/Managers/1/LogServices"}),
        )
        monkeypatch.setattr(client._managers, "get", lambda manager_id="1": manager)

        sel = Log.model_construct(
            id="Sel",
            odata_id="/redfish/v1/Managers/1/LogServices/Sel",
            entries=Link(**{"@odata.id": "/redfish/v1/Managers/1/LogServices/Sel/Entries"}),
        )
        entries = [
            LogEntry.model_construct(
                id="1", odata_id="/redfish/v1/Managers/1/LogServices/Sel/Entries/1"
            ),
            LogEntry.model_construct(
                id="2", odata_id="/redfish/v1/Managers/1/LogServices/Sel/Entries/2"
            ),
        ]

        collection_calls: List[Any] = []

        def fake_get_collection(odata_id, model_class):
            collection_calls.append((odata_id, model_class))
            if model_class is Log:
                return [sel]
            return entries

        monkeypatch.setattr(client, "_get_collection", fake_get_collection)

        result = client.get_manager_log_entries("Sel")
        assert result == entries
        assert collection_calls == [
            ("/redfish/v1/Managers/1/LogServices", Log),
            ("/redfish/v1/Managers/1/LogServices/Sel/Entries", LogEntry),
        ]
        client.close()

    def test_manager_no_log_services_link_raises(self, monkeypatch):
        client = _make_client()
        from redfish_sdk.models.managers import Manager

        manager = Manager.model_construct(id="1", odata_id="/redfish/v1/Managers/1")
        monkeypatch.setattr(client._managers, "get", lambda manager_id="1": manager)

        with pytest.raises(RedfishException, match="LogServices"):
            client.get_manager_log_entries()
        client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
