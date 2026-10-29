"""
Managers manager — manages BMC (Baseboard Management Controller) resources.

Provides access to:
- Manager info (BMC firmware version, model, etc.)
- Log services and log entries
- Network protocol configuration
- Ethernet interfaces
- Host interfaces
- KVM service configuration (OEM extension)

"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import urlsplit

from .. import models
from ..exceptions import RedfishNotFoundError, RedfishValidationError
from ..models.actions import ActionInfo
from ..models.common import Collection, Link, RedfishResponse
from ..models.logs import Log, LogActions, LogEntry
from ..models.managers import (
    DnsService,
    EthernetInterface,
    FirewallRules,
    HostInterface,
    HttpsCert,
    KvmService,
    LldpService,
    Manager,
    ManagerActions,
    ManagerResetRequest,
    NetworkProtocol,
    NtpService,
    SecurityService,
    SerialInterface,
    SerialInterfacePatch,
    SnmpService,
    SolSourceControlInfo,
    SyslogService,
    VirtualMedia,
    VirtualMediaEjectMediaRequest,
    VirtualMediaInsertMediaRequest,
    VncService,
)
from ..models.task import Task
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


class ManagersManager:
    """
    Manages Redfish Manager resources (BMC).


    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def get(self, manager_id: Optional[str] = "1") -> Manager:
        """
        Get a manager (BMC) resource by ID.



        Args:
            manager_id: Manager ID. ``None`` uses the compatibility default
                ``"1"``. If that member is not found, the advertised
                Managers collection is used as a fallback.

        Returns:
            Manager resource
        """
        manager_id = manager_id or "1"

        if manager_id != "1":
            return select_member(
                self._client._get_managers_collection(), manager_id
            )

        managers_odata_id = self._client._get_managers_collection_odata_id()
        resource_url = f"{managers_odata_id}/{manager_id}"
        try:
            return self._http.get(resource_url, Manager)
        except RedfishNotFoundError:
            if manager_id != "1":
                raise
            manager_members = self._client._get_managers_collection()
            if not manager_members:
                raise
            return manager_members[0]

    def log_services(self, manager_id: Optional[str] = None) -> List[Log]:
        """
        Get the list of log services for a manager (BMC).


        """
        from ._log_helpers import require_log_services_link

        manager = self.get(manager_id)
        odata_id = require_log_services_link(manager, f"Manager {manager.id!r}")
        return self._client._get_collection(odata_id, Log)

    def reset(self, reset_type: str = "ForceRestart", manager_id: Optional[str] = None) -> RedfishResponse:
        manager = self.get(manager_id)
        action = ManagerActions.model_validate(manager.actions or {}).manager_reset
        if not action or not action.target:
            raise RedfishValidationError("Manager does not advertise #Manager.Reset with an action target")
        allowed = action.reset_type_allowable_values
        if allowed is None and action.action_info:
            info = self._http.get(action.action_info, ActionInfo)
            allowed = info.allowable_values(ManagerResetRequest.model_fields["reset_type"].alias)
        if not reset_type or (allowed is not None and reset_type not in allowed):
            raise RedfishValidationError(f"Unsupported ResetType {reset_type!r}; advertised values: {allowed}")
        return self._http.post(action.target, RedfishResponse, body=ManagerResetRequest(reset_type=reset_type))

    def log_service(self, log_id: Optional[str] = None, manager_id: Optional[str] = None) -> Log:
        from ._log_helpers import require_log_services_link, resolve_log_service

        manager = self.get(manager_id)
        path = require_log_services_link(manager, f"Manager {manager.id!r}")
        return resolve_log_service(self._client, path, log_id)

    def clear_log(self, log_id: Optional[str] = None, manager_id: Optional[str] = None) -> None:
        log = self.log_service(log_id, manager_id)
        action = LogActions.model_validate(log.actions or {}).clear_log
        if not action or not action.target:
            raise RedfishValidationError(f"Manager log {log.id!r} does not advertise #LogService.ClearLog")
        self._http.post(action.target, RedfishResponse, raw_body={})

    def log_entries(
        self,
        log_id: Optional[str] = None,
        manager_id: Optional[str] = None,
    ) -> List[LogEntry]:
        """
        Get log entries for a manager (BMC) log service.

        Dynamic Entries link discovery + per-entry GET fallback;
        ``log_id`` is optional. See
        :meth:`SystemsManager.log_entries` for the full behaviour contract.
        """
        from ._log_helpers import (
            fetch_log_entries,
            require_log_services_link,
            resolve_log_service,
        )

        manager = self.get(manager_id)
        odata_id = require_log_services_link(manager, f"Manager {manager.id!r}")
        log = resolve_log_service(self._client, odata_id, log_id)
        return fetch_log_entries(self._client, log)

    # ------------------------------------------------------------------
    # Out-of-band diagnostic log collection + download
    # ------------------------------------------------------------------

    def collect_diagnostic_data(
        self,
        diagnostic_data_type: Optional[str] = None,
        log_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        oem_params: Optional[dict] = None,
    ) -> Task:
        """
        Trigger ``#LogService.CollectDiagnosticData`` on a manager log service.

        Automatically detects the server vendor and builds the vendor-specific
        request body. The action target is discovered dynamically from the
        LogService ``Actions`` block (never string-concatenated).

        Args:
            diagnostic_data_type: ``DiagnosticDataType`` value; ``None`` uses
                the vendor default (OEM when available, else ``Manager``).
            log_id: Log service ID. ``None`` auto-selects the sole service.
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.
            oem_params: Optional dict shallow-merged into the request body.

        Returns:
            A :class:`Task` referencing the asynchronous collection.

        Raises:
            RedfishValidationError: When the log service does not expose the
                ``#LogService.CollectDiagnosticData`` action.
        """
        from .log_collect_strategies import (
            LogCollectStrategyRegistry,
            VendorDetector,
        )

        vendor = VendorDetector.detect(self._client)
        strategy = LogCollectStrategyRegistry.get(vendor)
        odata_id = strategy.resolve_log_services_odata_id(
            self._client, manager_id
        )

        logger.info(
            "CollectDiagnosticData: vendor=%s, strategy=%s, log_services=%s",
            vendor, type(strategy).__name__, odata_id,
        )
        return strategy.trigger(
            self._client,
            odata_id,
            log_id=log_id,
            diagnostic_data_type=diagnostic_data_type,
            oem_params=oem_params,
            manager_id=manager_id,
        )

    def download_diagnostic_data(
        self,
        task_or_entry,
        output_path: Optional[str] = None,
    ) -> bytes | str:
        """
        Download the artifact produced by a diagnostic-data collection.

        Args:
            task_or_entry: A completed :class:`Task` (its associated log entry
                is resolved to find the artifact URI) or a :class:`LogEntry`
                that already carries ``AdditionalDataURI``.
            output_path: When provided, stream the bundle to this path and
                return the absolute file path; otherwise return ``bytes``.

        Returns:
            The file bytes, or the absolute written path.

        Raises:
            RedfishValidationError: When no artifact URI can be resolved.
            RedfishException: On download HTTP errors.
        """
        from ..models.logs import LogEntry
        from .log_collect_strategies import (
            LogCollectStrategyRegistry,
            VendorDetector,
        )

        # A LogEntry already carries the artifact URI -> plain GET download.
        if isinstance(task_or_entry, LogEntry):
            uri = task_or_entry.additional_data_uri
            if not uri:
                raise RedfishValidationError(
                    "LogEntry has no AdditionalDataURI to download"
                )
            logger.info("Downloading diagnostic data from %s", uri)
            return self._http.download(uri, output_path)

        # A Task -> let the vendor strategy decide how to fetch the bundle
        # (standard AdditionalDataURI GET, or an OEM POST download).
        if isinstance(task_or_entry, Task):
            vendor = VendorDetector.detect(self._client)
            strategy = LogCollectStrategyRegistry.get(vendor)
            return strategy.download_artifact(self._client, task_or_entry, output_path)

        # Duck-typed fallback: object exposing additional_data_uri.
        uri = getattr(task_or_entry, "additional_data_uri", None)
        if not uri:
            raise RedfishValidationError(
                "Could not resolve a diagnostic-data download URI"
            )
        logger.info("Downloading diagnostic data from %s", uri)
        return self._http.download(uri, output_path)

    def collect_and_download_diagnostic_data(
        self,
        output_path: str,
        diagnostic_data_type: Optional[str] = None,
        log_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        poll_interval: int = 5,
        timeout: int = 1800,
        *,
        reuse_existing: bool = True,
        max_retries: int = 0,
        retry_backoff: int = 30,
    ) -> str:
        """
        End-to-end helper: trigger collection, wait, then download.

        Chains :meth:`collect_diagnostic_data` -> :meth:`wait_for_task` (or a
        vendor-specific waiter) -> :meth:`download_diagnostic_data`.

        Resilience:
        - **Reuse of prior collections** (``reuse_existing=True``, default):
          before triggering a new collection, the strategy is asked whether
          the BMC already has a matching task. If found and already
          ``Completed``, its artifact is downloaded directly (avoids piling
          up tasks on BMCs that don't allow concurrent collections or that
          break after repeated triggers). If found and still ``Running``, the
          waiter runs on it directly instead of triggering a duplicate.
        - **Retry** (``max_retries`` > 0): a failed collection
          (:class:`LogCollectFailedError`) is retried up to ``max_retries``
          extra times with ``retry_backoff`` seconds between attempts. Retry
          is opt-in because a full collection is slow (minutes).

        Args:
            output_path: Destination file path for the downloaded bundle.
            diagnostic_data_type: See :meth:`collect_diagnostic_data`.
            log_id: See :meth:`collect_diagnostic_data`.
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.
            poll_interval: Task poll interval in seconds (default 5).
            timeout: Max wait in seconds (default 1800 — bundles are slow).
            reuse_existing: When True (default), look for a matching prior
                task and reuse its artifact/wait on it. Set False to always
                trigger a fresh collection.
            max_retries: Extra retries after a failed collection (default 0
                — no retry). Applies only to trigger-and-wait failures; a
                reused prior task is never retried.
            retry_backoff: Seconds to sleep between retries (default 30).

        Returns:
            The absolute path of the downloaded file.

        Raises:
            LogCollectFailedError: When collection ultimately fails (all
                retries exhausted); carries BMC messages / progress history.
        """
        import time as _time

        from ..exceptions import LogCollectFailedError
        from .log_collect_strategies import (
            LogCollectStrategyRegistry,
            VendorDetector,
        )

        vendor = VendorDetector.detect(self._client)
        strategy = LogCollectStrategyRegistry.get(vendor)

        # --- Step 1: reuse a prior collection when available -------------
        if reuse_existing:
            existing = self._find_existing_collect_task(strategy, manager_id)
            if existing is not None:
                state = (existing.task_state or "").lower()
                if state == "completed":
                    logger.info(
                        "collect_and_download: reusing completed prior task %r",
                        existing.id,
                    )
                    return strategy.download_artifact(
                        self._client, existing, output_path
                    )
                # Non-terminal -> just wait on it.
                logger.info(
                    "collect_and_download: waiting on in-flight prior task %r",
                    existing.id,
                )
                finished = strategy.wait_until_ready(
                    self._client, existing, poll_interval, timeout
                )
                return strategy.download_artifact(
                    self._client, finished, output_path
                )

        # --- Step 2: trigger + wait + download, with optional retry ------
        last_exc: Optional[LogCollectFailedError] = None
        attempts = max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                task = self.collect_diagnostic_data(
                    diagnostic_data_type, log_id, manager_id, oem_params=None
                )
                finished = strategy.wait_until_ready(
                    self._client, task, poll_interval, timeout
                )
                return strategy.download_artifact(
                    self._client, finished, output_path
                )
            except LogCollectFailedError as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "collect_and_download: attempt %d/%d failed (%s); "
                    "retrying in %ds",
                    attempt, attempts, exc, retry_backoff,
                )
                _time.sleep(max(int(retry_backoff), 0))

        assert last_exc is not None
        raise last_exc

    def _find_existing_collect_task(
        self, strategy, manager_id: Optional[str]
    ) -> Optional[Task]:
        """Resolve LogServices link then ask the strategy for a prior task."""
        try:
            odata_id = strategy.resolve_log_services_odata_id(
                self._client, manager_id
            )
        except Exception as exc:  # noqa: BLE001 — reuse discovery is best-effort
            logger.debug(
                "collect_and_download: skip reuse discovery (%s)", exc
            )
            return None
        try:
            return strategy.find_existing_task(
                self._client, odata_id, manager_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "collect_and_download: find_existing_task failed (%s)", exc
            )
            return None

    def network_protocol(self, manager_id: Optional[str] = None) -> NetworkProtocol:
        """
        Get network protocol configuration for a manager.


        """
        manager = self.get(manager_id)
        path = manager.network_protocol and manager.network_protocol.odata_id
        return self._http.get(
            path or f"{manager.odata_id}/NetworkProtocol", NetworkProtocol
        )

    def https_certificates(self, manager_id: Optional[str] = None) -> Collection[Link]:
        """Get the DMTF-standard HTTPS certificate collection.

        Discovers ``ManagerNetworkProtocol.HTTPS.Certificates`` rather than
        constructing a vendor-specific URI. For legacy OEM certificate
        resources, use :meth:`https_cert` as a separate fallback.
        """
        protocol = self.network_protocol(manager_id)
        certificates = protocol.https and protocol.https.certificates
        if not certificates or not certificates.odata_id:
            raise RedfishNotFoundError(
                f"{protocol.odata_id}/HTTPS/Certificates"
            )
        return self._http.get(certificates.odata_id, Collection[Link])

    def ethernet_interfaces(self, manager_id: Optional[str] = None) -> List[EthernetInterface]:
        """
        Get the list of Ethernet interfaces for a manager (BMC).


        """
        manager = self.get(manager_id)
        return self._client._get_collection(
            manager.ethernet_interfaces.odata_id, EthernetInterface
        )

    def host_interfaces(self, manager_id: Optional[str] = None) -> List[HostInterface]:
        """
        Get the list of host interfaces for a manager.


        """
        manager = self.get(manager_id)
        return self._client._get_collection(
            manager.host_interfaces.odata_id, HostInterface
        )

    def kvm_service(self, manager_id: Optional[str] = None) -> KvmService:
        """
        Get KVM service configuration from OEM links.

        The KVM service URI is dynamically discovered from the Manager's
        ``Oem.{vendor}.KVM`` link rather than being hardcoded.
        For standard console availability, prefer ``Manager.GraphicalConsole``.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            KvmService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose a KVM link
        """
        manager = self.get(manager_id)

        # Discover KVM URI from OEM links
        kvm_link = None
        if manager.oem and manager.oem.bmc:
            bmc = manager.oem.bmc
            # Check both "KVM" and "KvmService" OEM keys (vendor-dependent)
            if bmc.kvm_service and bmc.kvm_service.odata_id:
                kvm_link = bmc.kvm_service.odata_id
            elif bmc.kvm and bmc.kvm.odata_id:
                kvm_link = bmc.kvm.odata_id

        if not kvm_link:
            raise RedfishNotFoundError(
                f"{manager.odata_id}/KvmService"
            )

        return self._http.get(kvm_link, KvmService)

    # ------------------------------------------------------------------
    # OEM service helpers (batch SDK-GAP elimination)
    # ------------------------------------------------------------------

    def _get_oem_service(self, manager_id: Optional[str], attr: str, fallback_attr: str | None,
                         model_class, resource_label: str):
        """
        Generic helper to discover and fetch an OEM service resource.

        Checks ``manager.oem.bmc.{attr}`` (and optionally ``{fallback_attr}``)
        for the ``@odata.id`` link.

        Args:
            manager_id: Manager ID
            attr: Primary attribute name on the Bmc model
            fallback_attr: Optional fallback attribute name
            model_class: Pydantic model class to parse into
            resource_label: Human-readable name for error messages

        Returns:
            Parsed model instance

        Raises:
            RedfishNotFoundError: If the OEM link is not found
        """
        manager = self.get(manager_id)
        link = None
        if manager.oem and manager.oem.bmc:
            bmc = manager.oem.bmc
            primary = getattr(bmc, attr, None)
            if primary and primary.odata_id:
                link = primary.odata_id
            elif fallback_attr:
                fallback = getattr(bmc, fallback_attr, None)
                if fallback and fallback.odata_id:
                    link = fallback.odata_id

        if not link:
            raise RedfishNotFoundError(
                f"{manager.odata_id}/{resource_label}"
            )

        return self._http.get(link, model_class)

    def ntp_service(self, manager_id: Optional[str] = None) -> NtpService:
        """
        Get NTP service configuration from OEM links.

        Prefer the DMTF-standard ``ManagerNetworkProtocol.NTP`` section. This
        helper is only an optional, dynamically discovered OEM fallback.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            NtpService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose NtpService
        """
        return self._get_oem_service(
            manager_id, "ntp_service", None, NtpService, "NtpService"
        )

    def syslog_service(self, manager_id: Optional[str] = None) -> SyslogService:
        """
        Get Syslog service configuration from OEM links.

        DMTF Redfish has no generic Manager syslog-configuration resource;
        do not treat this optional OEM helper as a compliance requirement.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            SyslogService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose SyslogService
        """
        return self._get_oem_service(
            manager_id, "syslog_service", None, SyslogService, "SyslogService"
        )

    def snmp_service(self, manager_id: Optional[str] = None) -> SnmpService:
        """
        Get SNMP service configuration from OEM links.

        Prefer the DMTF-standard ``ManagerNetworkProtocol.SNMP`` section.
        This helper is only an optional, dynamically discovered OEM fallback.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            SnmpService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose SnmpService
        """
        return self._get_oem_service(
            manager_id, "snmp_service", None, SnmpService, "SnmpService"
        )

    def lldp_service(self, manager_id: Optional[str] = None) -> LldpService:
        """
        Get LLDP service configuration from OEM links.

        DMTF Redfish has no generic Manager LLDP service resource; this
        optional helper must not be required from standards-compliant BMCs.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            LldpService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose LldpService
        """
        return self._get_oem_service(
            manager_id, "lldp_service", None, LldpService, "LldpService"
        )

    def dns_service(self, manager_id: Optional[str] = None) -> DnsService:
        """
        Get DNS service configuration from OEM links.

        Prefer ``EthernetInterface.NameServers`` and
        ``ManagerNetworkProtocol.HostName``. This optional helper is a
        dynamically discovered OEM fallback and is not required by DMTF.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            DnsService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose DnsService
        """
        return self._get_oem_service(
            manager_id, "dns_service", None, DnsService, "DnsService"
        )

    def vnc_service(self, manager_id: Optional[str] = None) -> VncService:
        """
        Get VNC/RFB service configuration from OEM links.

        Prefer the DMTF-standard ``ManagerNetworkProtocol.RFB`` section.
        This helper is only an optional, dynamically discovered OEM fallback.

        Note: The OEM key is ``RfbService`` but the resource URI is
        ``VncService``.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            VncService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose VncService
        """
        return self._get_oem_service(
            manager_id, "rfb_service", None, VncService, "VncService"
        )

    def security_service(self, manager_id: Optional[str] = None) -> SecurityService:
        """
        Get Security service from OEM links.

        For HTTPS certificates, prefer
        ``ManagerNetworkProtocol.HTTPS.Certificates`` via
        :meth:`https_certificates`. This helper is an OEM fallback.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            SecurityService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose SecurityService
        """
        return self._get_oem_service(
            manager_id, "security_service", None, SecurityService, "SecurityService"
        )

    def https_cert(self, manager_id: Optional[str] = None) -> HttpsCert:
        """
        Get HTTPS certificate information via SecurityService links.

        Prefer :meth:`https_certificates`, which follows the DMTF-standard
        ``ManagerNetworkProtocol.HTTPS.Certificates`` link. This method keeps
        the legacy OEM ``SecurityService.Links.HttpsCert`` fallback available.

        Discovers SecurityService first, then follows its
        ``Links.HttpsCert`` link.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            HttpsCert resource

        Raises:
            RedfishNotFoundError: If HttpsCert link is not available
        """
        sec = self.security_service(manager_id)
        link = None
        if sec.links and sec.links.https_cert and sec.links.https_cert.odata_id:
            link = sec.links.https_cert.odata_id

        if not link:
            raise RedfishNotFoundError(
                f"{sec.odata_id}/HttpsCert"
            )

        return self._http.get(link, HttpsCert)

    def firewall_rules(self, manager_id: Optional[str] = None) -> FirewallRules:
        """
        Get Firewall rules collection from OEM links.

        DMTF Redfish has no generic Manager firewall-rules resource; this
        optional helper must not be required from standards-compliant BMCs.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            FirewallRules collection resource

        Raises:
            RedfishNotFoundError: If the manager does not expose FirewallRules
        """
        return self._get_oem_service(
            manager_id, "firewall_rules", None, FirewallRules, "FirewallRules"
        )

    def virtual_media(self, manager_id: Optional[str] = None) -> List[VirtualMedia]:
        """
        Get the list of virtual media resources for a manager.

        Uses the standard Redfish VirtualMedia collection link on the
        Manager resource. Falls back to the OEM link if the standard
        link is not present.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            List of VirtualMedia resources
        """
        manager = self.get(manager_id)

        # Standard Redfish path first
        vm_odata_id = manager.virtual_media and manager.virtual_media.odata_id

        # Fallback to OEM link
        if not vm_odata_id and manager.oem and manager.oem.bmc:
            oem_vm = manager.oem.bmc.virtual_media_oem
            if oem_vm and oem_vm.odata_id:
                vm_odata_id = oem_vm.odata_id

        # Last resort: construct from manager odata_id
        if not vm_odata_id:
            vm_odata_id = f"{manager.odata_id}/VirtualMedia"

        return self._client._get_collection(vm_odata_id, VirtualMedia)

    def virtual_media_resource(
        self,
        media_id: Optional[str] = None,
        manager_id: Optional[str] = None,
    ) -> VirtualMedia:
        """Return one advertised VirtualMedia resource without changing it."""
        return select_member(self.virtual_media(manager_id), media_id)

    def insert_virtual_media(
        self,
        image: str,
        media_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        *,
        inserted: Optional[bool] = None,
        write_protected: Optional[bool] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        transfer_method: Optional[str] = None,
        transfer_protocol_type: Optional[str] = None,
        http_headers: Optional[dict[str, str]] = None,
    ) -> RedfishResponse:
        """Invoke the advertised standard ``InsertMedia`` action."""
        media = self.virtual_media_resource(media_id, manager_id)
        action = media.actions and media.actions.insert_media
        if not action or not action.target:
            raise RedfishValidationError(
                f"VirtualMedia {media.id!r} does not advertise "
                "#VirtualMedia.InsertMedia with an action target"
            )

        supplied = {
            "Inserted": inserted,
            "WriteProtected": write_protected,
            "TransferMethod": transfer_method,
            "TransferProtocolType": transfer_protocol_type,
            "HTTPHeaders": http_headers,
        }
        if http_headers is not None:
            header_protocol = (
                transfer_protocol_type or urlsplit(image).scheme
            ).upper()
            if header_protocol and header_protocol not in {"HTTP", "HTTPS"}:
                raise RedfishValidationError(
                    "HTTPHeaders can only be used with HTTP or HTTPS media"
                )
        info = (
            self._http.get(action.action_info, ActionInfo)
            if action.action_info
            and any(value is not None for value in supplied.values())
            else None
        )
        inline_values = {
            "Inserted": action.inserted_allowable_values,
            "WriteProtected": action.write_protected_allowable_values,
            "TransferMethod": action.transfer_method_allowable_values,
            "TransferProtocolType": (
                action.transfer_protocol_type_allowable_values
            ),
        }
        for name, value in supplied.items():
            if value is None or name == "HTTPHeaders":
                continue
            allowed = inline_values[name]
            if allowed is None and info:
                allowed = info.allowable_values(name)
            if allowed is not None and value not in allowed:
                raise RedfishValidationError(
                    f"Unsupported {name} {value!r}; advertised values: {allowed}"
                )

        if http_headers is not None:
            action_advertises_headers = bool(
                info and info.parameter("HTTPHeaders")
            )
            if media.http_headers is None and not action_advertises_headers:
                raise RedfishValidationError(
                    "VirtualMedia does not advertise HTTPHeaders support"
                )

        request = VirtualMediaInsertMediaRequest(
            image=image,
            inserted=inserted,
            write_protected=write_protected,
            username=username,
            password=password,
            transfer_method=transfer_method,
            transfer_protocol_type=transfer_protocol_type,
            http_headers=http_headers,
        )
        return self._http.post(action.target, RedfishResponse, body=request)

    def eject_virtual_media(
        self,
        media_id: Optional[str] = None,
        manager_id: Optional[str] = None,
    ) -> RedfishResponse:
        """Invoke the advertised standard ``EjectMedia`` action."""
        media = self.virtual_media_resource(media_id, manager_id)
        action = media.actions and media.actions.eject_media
        if not action or not action.target:
            raise RedfishValidationError(
                f"VirtualMedia {media.id!r} does not advertise "
                "#VirtualMedia.EjectMedia with an action target"
            )
        return self._http.post(
            action.target, RedfishResponse, body=VirtualMediaEjectMediaRequest()
        )

    def serial_interfaces(self, manager_id: Optional[str] = None) -> List[SerialInterface]:
        manager = self.get(manager_id)
        link = manager.serial_interfaces
        if not link or not link.odata_id:
            raise RedfishNotFoundError("Manager does not advertise SerialInterfaces (IPMI SOL may be disabled)")
        return self._client._get_collection(link.odata_id, SerialInterface)

    def serial_interface(
        self, identifier: Optional[str] = None, manager_id: Optional[str] = None
    ) -> SerialInterface:
        return select_member(self.serial_interfaces(manager_id), identifier)

    def update_serial_interface(
        self, identifier: Optional[str] = None, manager_id: Optional[str] = None,
        *, interface_enabled: Optional[bool] = None, bit_rate: Optional[str] = None,
        data_bits: Optional[str] = None, stop_bits: Optional[str] = None,
        parity: Optional[str] = None, flow_control: Optional[str] = None,
    ) -> models.RedfishResponse:
        body = SerialInterfacePatch(
            interface_enabled=interface_enabled, bit_rate=bit_rate, data_bits=data_bits,
            stop_bits=stop_bits, parity=parity, flow_control=flow_control,
        )
        payload = body.model_dump(by_alias=True, exclude_none=True)
        if not payload:
            raise RedfishValidationError("Supply at least one serial configuration field")
        interface = self.serial_interface(identifier, manager_id)
        if not interface.odata_id:
            raise RedfishNotFoundError("SerialInterface does not advertise @odata.id")
        for name, value in payload.items():
            allowed = (interface.model_extra or {}).get(f"{name}@Redfish.AllowableValues")
            if allowed is not None and value not in allowed:
                raise RedfishValidationError(f"Unsupported {name} {value!r}; advertised values: {allowed}")
        body.odata_etag = interface.odata_etag
        return self._http.patch(interface.odata_id, models.RedfishResponse, body)

    def sol_source(self, manager_id: Optional[str] = None) -> SolSourceControlInfo:
        """
        Get SOL source control information from OEM links.

        Note: Not all BMC vendors support this endpoint.

        Args:
            manager_id: Manager ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            SolSourceControlInfo resource

        Raises:
            RedfishNotFoundError: If the manager does not expose SOLSourceControlInfo
        """
        return self._get_oem_service(
            manager_id, "sol_source_control_info", None,
            SolSourceControlInfo, "SOLSourceControlInfo"
        )
