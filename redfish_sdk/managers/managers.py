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
    EthernetInterface,
    HostInterface,
    KvmService,
    Manager,
    NetworkProtocol,
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
