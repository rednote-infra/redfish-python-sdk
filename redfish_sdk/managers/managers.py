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

from ..models.logs import Log, LogEntry
from ..exceptions import RedfishNotFoundError
from ..models.managers import (
    DnsService,
    EthernetInterface,
    FirewallRules,
    HostInterface,
    HttpsCert,
    KvmService,
    LldpService,
    Manager,
    NetworkProtocol,
    NtpService,
    SecurityService,
    SnmpService,
    SolSourceControlInfo,
    SyslogService,
    VirtualMedia,
    VncService,
)

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

    def get(self, manager_id: str = "1") -> Manager:
        """
        Get a manager (BMC) resource by ID.



        Args:
            manager_id: Manager ID (default "1")

        Returns:
            Manager resource
        """
        managers_odata_id = self._client._get_managers_collection_odata_id()
        return self._http.get(
            f"{managers_odata_id}/{manager_id}", Manager
        )

    def log_services(self, manager_id: str = "1") -> List[Log]:
        """
        Get the list of log services for a manager (BMC).


        """
        from ._log_helpers import require_log_services_link

        manager = self.get(manager_id)
        odata_id = require_log_services_link(manager, f"Manager {manager.id!r}")
        return self._client._get_collection(odata_id, Log)

    def log_entries(
        self,
        log_id: Optional[str] = None,
        manager_id: str = "1",
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

    def network_protocol(self, manager_id: str = "1") -> NetworkProtocol:
        """
        Get network protocol configuration for a manager.


        """
        manager = self.get(manager_id)
        return self._http.get(
            f"{manager.odata_id}/NetworkProtocol", NetworkProtocol
        )

    def ethernet_interfaces(self, manager_id: str = "1") -> List[EthernetInterface]:
        """
        Get the list of Ethernet interfaces for a manager (BMC).


        """
        manager = self.get(manager_id)
        return self._client._get_collection(
            manager.ethernet_interfaces.odata_id, EthernetInterface
        )

    def host_interfaces(self, manager_id: str = "1") -> List[HostInterface]:
        """
        Get the list of host interfaces for a manager.


        """
        manager = self.get(manager_id)
        return self._client._get_collection(
            manager.host_interfaces.odata_id, HostInterface
        )

    def kvm_service(self, manager_id: str = "1") -> KvmService:
        """
        Get KVM service configuration from OEM links.

        The KVM service URI is dynamically discovered from the Manager's
        ``Oem.{vendor}.KVM`` link rather than being hardcoded.

        Args:
            manager_id: Manager ID (default "1")

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

    def _get_oem_service(self, manager_id: str, attr: str, fallback_attr: str | None,
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

    def ntp_service(self, manager_id: str = "1") -> NtpService:
        """
        Get NTP service configuration from OEM links.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            NtpService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose NtpService
        """
        return self._get_oem_service(
            manager_id, "ntp_service", None, NtpService, "NtpService"
        )

    def syslog_service(self, manager_id: str = "1") -> SyslogService:
        """
        Get Syslog service configuration from OEM links.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            SyslogService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose SyslogService
        """
        return self._get_oem_service(
            manager_id, "syslog_service", None, SyslogService, "SyslogService"
        )

    def snmp_service(self, manager_id: str = "1") -> SnmpService:
        """
        Get SNMP service configuration from OEM links.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            SnmpService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose SnmpService
        """
        return self._get_oem_service(
            manager_id, "snmp_service", None, SnmpService, "SnmpService"
        )

    def lldp_service(self, manager_id: str = "1") -> LldpService:
        """
        Get LLDP service configuration from OEM links.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            LldpService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose LldpService
        """
        return self._get_oem_service(
            manager_id, "lldp_service", None, LldpService, "LldpService"
        )

    def dns_service(self, manager_id: str = "1") -> DnsService:
        """
        Get DNS service configuration from OEM links.

        Note: Not all BMC vendors support this endpoint.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            DnsService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose DnsService
        """
        return self._get_oem_service(
            manager_id, "dns_service", None, DnsService, "DnsService"
        )

    def vnc_service(self, manager_id: str = "1") -> VncService:
        """
        Get VNC/RFB service configuration from OEM links.

        Note: The OEM key is ``RfbService`` but the resource URI is
        ``VncService``.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            VncService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose VncService
        """
        return self._get_oem_service(
            manager_id, "rfb_service", None, VncService, "VncService"
        )

    def security_service(self, manager_id: str = "1") -> SecurityService:
        """
        Get Security service from OEM links.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            SecurityService resource

        Raises:
            RedfishNotFoundError: If the manager does not expose SecurityService
        """
        return self._get_oem_service(
            manager_id, "security_service", None, SecurityService, "SecurityService"
        )

    def https_cert(self, manager_id: str = "1") -> HttpsCert:
        """
        Get HTTPS certificate information via SecurityService links.

        Discovers SecurityService first, then follows its
        ``Links.HttpsCert`` link.

        Args:
            manager_id: Manager ID (default "1")

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

    def firewall_rules(self, manager_id: str = "1") -> FirewallRules:
        """
        Get Firewall rules collection from OEM links.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            FirewallRules collection resource

        Raises:
            RedfishNotFoundError: If the manager does not expose FirewallRules
        """
        return self._get_oem_service(
            manager_id, "firewall_rules", None, FirewallRules, "FirewallRules"
        )

    def virtual_media(self, manager_id: str = "1") -> List[VirtualMedia]:
        """
        Get the list of virtual media resources for a manager.

        Uses the standard Redfish VirtualMedia collection link on the
        Manager resource. Falls back to the OEM link if the standard
        link is not present.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            List of VirtualMedia resources
        """
        manager = self.get(manager_id)

        # Standard Redfish path first
        vm_odata_id = None
        if hasattr(manager, "model_extra") and manager.model_extra:
            vm_link = manager.model_extra.get("VirtualMedia")
            if isinstance(vm_link, dict) and "@odata.id" in vm_link:
                vm_odata_id = vm_link["@odata.id"]

        # Fallback to OEM link
        if not vm_odata_id and manager.oem and manager.oem.bmc:
            oem_vm = manager.oem.bmc.virtual_media_oem
            if oem_vm and oem_vm.odata_id:
                vm_odata_id = oem_vm.odata_id

        # Last resort: construct from manager odata_id
        if not vm_odata_id:
            vm_odata_id = f"{manager.odata_id}/VirtualMedia"

        return self._client._get_collection(vm_odata_id, VirtualMedia)

    def sol_source(self, manager_id: str = "1") -> SolSourceControlInfo:
        """
        Get SOL source control information from OEM links.

        Note: Not all BMC vendors support this endpoint.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            SolSourceControlInfo resource

        Raises:
            RedfishNotFoundError: If the manager does not expose SOLSourceControlInfo
        """
        return self._get_oem_service(
            manager_id, "sol_source_control_info", None,
            SolSourceControlInfo, "SOLSourceControlInfo"
        )
