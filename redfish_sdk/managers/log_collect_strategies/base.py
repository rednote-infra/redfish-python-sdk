"""
Base log-collect strategy and the generic (standard Redfish) implementation.

Vendor strategies inherit from :class:`BaseLogCollectStrategy` and customise
how diagnostic-data collection is triggered and how the produced bundle is
downloaded. Two levels of extension points are provided:

Low-level (standard ``#LogService.CollectDiagnosticData`` flow):
    - :meth:`build_body` — the request body.
    - :meth:`extract_download_uri` — where the artifact URI lives.

High-level (whole-flow override, for OEM schemes that don't fit the standard):
    - :meth:`discover_collect_target` — which URL to POST to trigger.
    - :meth:`build_collect_body` — the trigger request body.
    - :meth:`download_artifact` — how to fetch the finished bundle.

The generic strategy implements the standard DMTF flow; e.g. Inspur overrides
the high-level hooks to use a collection-level OEM ``CollectAllLog`` /
``DownloadAllLog`` pair.

The design mirrors ``update_strategies`` so the two multi-vendor features
share the same mental model: an abstract base, a generic fallback, a
registry of singletons, and runtime vendor detection.
"""
from __future__ import annotations

import logging
from abc import ABC
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.logs import LogEntry
from ...models.task import Task

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

# DMTF standard default diagnostic data type when the caller does not
# specify one and the vendor strategy has no OEM-preferred value.
DEFAULT_DIAGNOSTIC_DATA_TYPE = "Manager"

# Standard per-LogService collection action name.
COLLECT_ACTION = "#LogService.CollectDiagnosticData"


class BaseLogCollectStrategy(ABC):
    """
    Abstract base class for out-of-band log collection strategies.

    The default implementation follows the standard DMTF
    ``#LogService.CollectDiagnosticData`` flow. Vendors whose BMC uses a
    different scheme override the high-level hooks
    (:meth:`discover_collect_target`, :meth:`build_collect_body`,
    :meth:`download_artifact`).
    """

    #: Vendor-preferred diagnostic data type when the caller passes ``None``.
    #: ``None`` here means "fall back to the DMTF standard default".
    default_diagnostic_data_type: Optional[str] = None

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    def discover_collect_target(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        log_id: Optional[str],
    ) -> Optional[str]:
        """
        Return the action URL used to trigger collection, or ``None``.

        Standard behaviour: resolve a single LogService (auto-selecting the
        only one exposing ``CollectDiagnosticData`` when ``log_id`` is None)
        and return its action target. Vendors that publish a collection-level
        OEM action override this.
        """
        from .._log_helpers import _describe_services, resolve_log_service
        from ..systems import _extract_action_target
        from ...exceptions import RedfishValidationError, RedfishException
        from ...models.logs import Log

        if log_id is not None:
            log = resolve_log_service(client, log_services_odata_id, log_id)
            return _extract_action_target(log.actions, COLLECT_ACTION)

        services = client._get_collection(log_services_odata_id, Log)
        if not services:
            raise RedfishException(
                404, f"No log services found under {log_services_odata_id}"
            )
        if len(services) == 1:
            return _extract_action_target(services[0].actions, COLLECT_ACTION)

        supported = []
        for svc in services:
            if not svc.odata_id:
                continue
            try:
                full = client._http_client.get(svc.odata_id, Log)
            except RedfishException:
                continue
            if _extract_action_target(full.actions, COLLECT_ACTION):
                supported.append(full)

        if len(supported) == 1:
            logger.info(
                "Auto-selected log service %r for CollectDiagnosticData",
                supported[0].id,
            )
            return _extract_action_target(supported[0].actions, COLLECT_ACTION)
        if not supported:
            raise RedfishValidationError(
                f"No log service under {log_services_odata_id} exposes "
                f"{COLLECT_ACTION}. Available: {_describe_services(services)}"
            )
        raise RedfishValidationError(
            f"Multiple log services support CollectDiagnosticData, "
            f"please specify log_id. Candidates: {_describe_services(supported)}"
        )

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
        """
        Trigger collection and return a Task. Standard: discover the action
        target, build the body, POST it and parse a Redfish Task.

        Vendors whose trigger response is not a Redfish Task (e.g. ZTE returns
        a plain success message and tracks progress separately) override this
        and return a synthetic Task carrying the context they need later.
        """
        from ...exceptions import RedfishValidationError

        target = self.discover_collect_target(
            client, log_services_odata_id, log_id
        )
        if not target:
            raise RedfishValidationError(
                f"No diagnostic-data collection action found under "
                f"{log_services_odata_id} (strategy={type(self).__name__})"
            )
        body = self.build_collect_body(diagnostic_data_type, oem_params)
        logger.info("Collect trigger POST %s body=%s", target, body)
        return client._http_client.post(target, Task, raw_body=body)

    def resolve_diagnostic_data_type(
        self, diagnostic_data_type: Optional[str]
    ) -> str:
        """
        Resolve the effective ``DiagnosticDataType``.

        Priority: explicit caller value > vendor default > DMTF default.
        """
        if diagnostic_data_type:
            return diagnostic_data_type
        return self.default_diagnostic_data_type or DEFAULT_DIAGNOSTIC_DATA_TYPE

    def build_collect_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build the trigger request body. Standard: DMTF CollectDiagnosticData.
        """
        body: Dict[str, Any] = {
            "DiagnosticDataType": self.resolve_diagnostic_data_type(
                diagnostic_data_type
            ),
        }
        if oem_params:
            body.update(oem_params)
        return body

    # Backwards-compatible alias (older callers/tests used build_body).
    build_body = build_collect_body

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def extract_download_uri(
        self,
        client: "RedfishClient",
        task: Task,
    ) -> Optional[str]:
        """
        Locate the diagnostic-data artifact URI from a finished task.

        Standard behaviour reads the log entry referenced by the task and
        returns its ``AdditionalDataURI``. Returns ``None`` when unresolved.
        """
        entry = _resolve_task_log_entry(client, task)
        if entry is not None and entry.additional_data_uri:
            return entry.additional_data_uri
        return None

    def wait_until_ready(
        self,
        client: "RedfishClient",
        task: Task,
        poll_interval: int = 5,
        timeout: int = 1800,
    ) -> Task:
        """
        Block until the collection is ready, then return the finished task.

        Standard behaviour polls the Redfish TaskService via
        ``wait_for_task`` and validates the terminal state. Vendors whose
        progress is tracked outside TaskService (e.g. ZTE's bespoke
        ``Dump/Progress`` endpoint) override this.

        Raises:
            LogCollectFailedError: When the task ends in a non-OK terminal
                state; carries the full BMC messages for diagnosis.
            RedfishException: When there is no Task id to poll.
        """
        from ...exceptions import LogCollectFailedError, RedfishException

        # Prefer the id parsed from ``@odata.id`` because some BMCs
        # (smoothcompute 6415 X2, observed in the wild) put a human-friendly
        # name — e.g. "CollectBlackBox" — into the ``Id`` field of the trigger
        # response while the actual TaskService key sits in the URL path
        # (``/redfish/v1/TaskService/Tasks/1``). Falling back to ``task.id``
        # keeps compatibility with BMCs that populate it correctly.
        task_id: Optional[str] = None
        if task.odata_id:
            tail = task.odata_id.rstrip("/").rsplit("/", 1)[-1]
            if tail:
                task_id = tail
        if not task_id:
            task_id = task.id
        if not task_id:
            raise RedfishException(
                500,
                "Collection did not return a Task id; cannot poll for completion",
            )

        finished = client.wait_for_task(task_id, poll_interval, timeout)
        state = finished.task_state or ""
        status = finished.task_status or ""
        if state != "Completed" or (status and status != "OK"):
            raise LogCollectFailedError(
                _format_failure_message(task_id, state, status, finished.messages),
                task_id=str(task_id),
                task_state=state,
                task_status=status,
                messages=_serialise_messages(finished.messages),
            )
        return finished

    # ------------------------------------------------------------------
    # Existing-task discovery (for reusing a previous collection artifact)
    # ------------------------------------------------------------------

    def find_existing_task(
        self,
        client: "RedfishClient",
        log_services_odata_id: str,
        manager_id: str = "1",
    ) -> Optional[Task]:
        """
        Return the most recent collection task on the BMC, or ``None``.

        The default implementation walks ``/redfish/v1/TaskService/Tasks`` and
        keeps tasks whose ``Payload.TargetUri`` targets a
        ``CollectDiagnosticData`` action; the newest match (by ``StartTime``
        when available, else by id) is returned. This lets
        :meth:`ManagersManager.collect_and_download_diagnostic_data` reuse a
        prior artifact instead of triggering a redundant (or failing) run.

        Vendors whose progress is not exposed via TaskService (e.g. ZTE)
        override this. Returning ``None`` means "no prior task to reuse; go
        ahead and trigger a fresh collection".
        """
        from ...exceptions import RedfishException

        try:
            tasks = client.get_tasks()
        except RedfishException as exc:
            logger.debug("find_existing_task: enumerate failed: %s", exc)
            return None

        matches = []
        for t in tasks:
            if not t.odata_id:
                continue
            try:
                raw = client._http_client.get_raw(t.odata_id)
            except RedfishException:
                continue
            if _looks_like_collect_task(raw):
                # Re-parse to catch any fields the collection listing dropped.
                matches.append((raw.get("StartTime") or "", raw))

        if not matches:
            return None

        matches.sort(key=lambda x: x[0], reverse=True)
        newest_raw = matches[0][1]
        logger.info(
            "find_existing_task: reusing Task %s (state=%s)",
            newest_raw.get("@odata.id"),
            newest_raw.get("TaskState"),
        )
        return Task.model_validate(newest_raw)

    def download_artifact(
        self,
        client: "RedfishClient",
        task: Task,
        output_path: Optional[str] = None,
    ) -> "bytes | str":
        """
        Download the produced bundle. Standard: resolve ``AdditionalDataURI``
        then GET it. Vendors with a POST-download action override this.

        Raises:
            RedfishValidationError: When no artifact URI can be resolved.
        """
        from ...exceptions import RedfishValidationError

        uri = self.extract_download_uri(client, task)
        if not uri:
            raise RedfishValidationError(
                "Could not resolve a diagnostic-data download URI "
                "(no AdditionalDataURI on the task or log entry)"
            )
        logger.info("Downloading diagnostic data from %s", uri)
        return client._http_client.download(uri, output_path)


class GenericLogCollectStrategy(BaseLogCollectStrategy):
    """
    Standard Redfish ``CollectDiagnosticData`` strategy (fallback).

    Used when the server vendor is not recognised. Sends the DMTF-standard
    body and reads ``AdditionalDataURI`` from the produced log entry.
    """


def _serialise_messages(messages) -> list:
    """
    Convert a Task's ``Messages`` list to plain dicts, preserving the fields
    an operator needs to diagnose a failed collection.
    """
    out = []
    if not messages:
        return out
    for m in messages:
        # ``Message`` model — pydantic ``.model_dump`` if available, else best-
        # effort attribute copy.
        if hasattr(m, "model_dump"):
            try:
                out.append(m.model_dump(by_alias=True, exclude_none=True))
                continue
            except Exception:  # noqa: BLE001
                pass
        out.append({
            "MessageId": getattr(m, "message_id", None),
            "Message": getattr(m, "message", None),
            "Severity": getattr(m, "severity", None),
            "Resolution": getattr(m, "resolution", None),
        })
    return out


def _format_failure_message(
    task_id: str, state: str, status: str, messages
) -> str:
    """Build a human-readable one-line summary used as the exception text."""
    serialised = _serialise_messages(messages)
    highlights = []
    for m in serialised[-3:]:  # last few messages are usually the most useful
        mid = m.get("MessageId") or ""
        msg = m.get("Message") or ""
        if mid or msg:
            highlights.append(f"{mid}: {msg}".strip(": "))
    tail = f" | {' | '.join(highlights)}" if highlights else ""
    return (
        f"Diagnostic data collection task {task_id} did not succeed: "
        f"state={state!r}, status={status!r}{tail}"
    )


# Substrings inside ``Payload.TargetUri`` that identify a diagnostic-data
# collection task published on the standard TaskService.
_COLLECT_TARGET_HINTS = (
    "CollectDiagnosticData",
    "CollectAllLog",
    "LogServices.Dump",
)


def _looks_like_collect_task(raw: dict) -> bool:
    """Heuristic: does this Task's Payload target a log-collection action?"""
    if not isinstance(raw, dict):
        return False
    payload = raw.get("Payload") or {}
    target = payload.get("TargetUri") or ""
    if isinstance(target, str) and any(h in target for h in _COLLECT_TARGET_HINTS):
        return True
    # Fallback: the Task's ``Name`` sometimes reveals it (e.g. Inspur uses
    # "One-click log collection task").
    name = (raw.get("Name") or "").lower()
    return "log collect" in name or "diagnostic" in name


def _resolve_task_log_entry(
    client: "RedfishClient",
    task: Task,
) -> Optional[LogEntry]:
    """
    Best-effort resolution of the LogEntry a collection task produced.

    Strategy:
    1. If the task itself already carries ``AdditionalDataURI`` (some BMCs
       inline it), wrap it into a synthetic LogEntry.
    2. Otherwise inspect the task's ``Payload``/links for a log-entry link
       and GET it as a :class:`LogEntry`.

    Returns ``None`` when nothing can be resolved; callers then raise a
    descriptive error.
    """
    if task.odata_id:
        try:
            raw = client._http_client.get_raw(task.odata_id)
        except Exception:  # noqa: BLE001 — best-effort discovery
            raw = None
        if isinstance(raw, dict):
            uri = raw.get("AdditionalDataURI")
            if uri:
                return LogEntry.model_validate(raw)

            payload = raw.get("Payload") or {}
            target = payload.get("HttpOperation") and payload.get("TargetUri")
            entry_link = (
                raw.get("Links", {}).get("CreatedResources")
                or ([{"@odata.id": target}] if target else [])
            )
            for link in entry_link:
                link_id = link.get("@odata.id") if isinstance(link, dict) else None
                if link_id:
                    try:
                        return client._http_client.get(link_id, LogEntry)
                    except Exception:  # noqa: BLE001
                        continue
    return None
