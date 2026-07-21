"""
RedfishClient — the top-level entry point for the Redfish Python SDK.

Aggregates all service managers into a single object, providing a clean
and intuitive interface for interacting with a BMC via Redfish.

Usage:
    import os
    from redfish_sdk import RedfishClient

    # Credentials are read from environment variables:
    #   BMC_IP, BMC_USERNAME, BMC_PASSWORD
    client = RedfishClient(
        host=os.environ["BMC_IP"],
        username=os.environ["BMC_USERNAME"],
        password=os.environ["BMC_PASSWORD"],
    )

    # Get system info
    system = client.get_system()

    # List CPUs
    cpus = client.get_processors()

    # Reset server
    client.reset("GracefulRestart")

    # Close when done
    client.close()

    # Or use as context manager
    with RedfishClient(
        host=os.environ["BMC_IP"],
        username=os.environ["BMC_USERNAME"],
        password=os.environ["BMC_PASSWORD"],
    ) as client:
        system = client.get_system()

"""
from __future__ import annotations

import logging
from functools import cached_property
from typing import Any, Dict, List, Optional, Type, TypeVar

from .exceptions import RedfishException
from .http_client import RedfishHttpClient
from .models.account import Account, AccountService, Role
from .models.resource_key import RedfishResource
from .models.chassis import Chassis
from .models.drive import Drive
from .models.common import Collection, Entity, Link, RedfishResponse
from .models.event import EventService, Subscription
from .models.fru import Fru
from .models.logs import Log, LogEntry
from .models.oem import MainBoard
from .models.managers import EthernetInterface, HostInterface, Manager, NetworkProtocol
from .models.memory import Memory
from .models.power import Power, PowerSupply
from .models.processor import Processor
from .models.registry import Registry
from .models.root import RootService
from .models.session import Session, SessionService
from .models.systems import Bios, BootOption, System, SystemPatchSetting
from .models.task import Task, TaskService
from .models.thermal import Fan, InletHistoryTemperature, Thermal
from .models.update import ClientCertificate, FirmwareInventory, UpdateService

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Entity)

# Names of all cached_property manager attributes, used by close()
_MANAGER_ATTRS = (
    "_systems", "_chassis", "_managers", "_accounts",
    "_sessions", "_events", "_updates", "_registries", "_tasks",
)


class RedfishClient:
    """
    Top-level Redfish Client.

    Aggregates all service managers and provides the main entry point
    for interacting with a BMC via the Redfish protocol.

    All operations are accessible directly via ``client.get_xxx()`` /
    ``client.xxx()`` style methods.  The underlying service managers
    are private implementation details and should not be accessed
    directly.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        proxy: Optional[str] = None,
        connect_timeout: int = 10,
        read_timeout: int = 30,
        scheme: str = "https",
    ):
        """
        Initialize the Redfish Client.

        Args:
            host: BMC IP address or hostname (e.g., ``os.environ["BMC_IP"]``)
            username: BMC username (e.g., ``os.environ["BMC_USERNAME"]``)
            password: BMC password (e.g., ``os.environ["BMC_PASSWORD"]``)
            verify_ssl: Whether to verify SSL certificates.
                        Default False — BMCs typically use self-signed certificates.
            proxy: Optional HTTP/HTTPS proxy URL.
                   Example: "http://127.0.0.1:8080" (matches Java's proxy config)
            connect_timeout: TCP connection timeout in seconds (default 10)
            read_timeout: HTTP response read timeout in seconds (default 30)
            scheme: URL scheme — "https" (default) or "http"
        """
        self._http_client = RedfishHttpClient(
            host=host,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            proxy=proxy,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            scheme=scheme,
        )

        # Root service cache
        self._root_cache: Optional[RootService] = None

        logger.info("RedfishClient initialized for host: %s", host)

    # ------------------------------------------------------------------
    # Private manager accessors (lazy-loaded via cached_property)
    # ------------------------------------------------------------------

    @cached_property
    def _systems(self):
        from .managers.systems import SystemsManager
        return SystemsManager(self)

    @cached_property
    def _chassis(self):
        from .managers.chassis import ChassisManager
        return ChassisManager(self)

    @cached_property
    def _managers(self):
        from .managers.managers import ManagersManager
        return ManagersManager(self)

    @cached_property
    def _accounts(self):
        from .managers.account import AccountServiceManager
        return AccountServiceManager(self)

    @cached_property
    def _sessions(self):
        from .managers.session import SessionServiceManager
        return SessionServiceManager(self)

    @cached_property
    def _events(self):
        from .managers.event import EventServiceManager
        return EventServiceManager(self)

    @cached_property
    def _updates(self):
        from .managers.update import UpdateServiceManager
        return UpdateServiceManager(self)

    @cached_property
    def _registries(self):
        from .managers.registries import RegistriesManager
        return RegistriesManager(self)

    @cached_property
    def _tasks(self):
        from .managers.task import TaskServiceManager
        return TaskServiceManager(self)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def host(self) -> str:
        """Return the configured BMC host."""
        return self._http_client.host

    def root(self):
        """
        Get the Redfish root service document.
        Returns the raw RootService resource with all top-level links.
        """
        return self._get_root()

    def close(self) -> None:
        """Close the underlying HTTP session and free resources."""
        for attr in _MANAGER_ATTRS:
            self.__dict__.pop(attr, None)
        self._http_client.close()
        logger.info("RedfishClient closed for host: %s", self._http_client.host)

    def __enter__(self) -> RedfishClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"RedfishClient(host={self._http_client.host!r})"

    # ------------------------------------------------------------------
    # Core methods (absorbed from RootServiceManager)
    # ------------------------------------------------------------------

    def _get_root(self) -> RootService:
        """
        Fetch the Redfish root service document.
        Endpoint: GET /redfish/v1/
        """
        return self._http_client.get("/redfish/v1/", RootService)

    def _get_collection(self, odata_id: str, model_class: Type[T]) -> List[T]:
        """
        Generic collection fetcher.

        1. Fetches the collection index (Members list with @odata.id links)
        2. Individually fetches each member to get full details
        3. Returns a list of fully populated model instances

        Args:
            odata_id: The @odata.id of the collection resource
            model_class: The pydantic model class for collection members

        Returns:
            List of fully populated model instances
        """
        from pydantic import TypeAdapter

        # Step 1: fetch collection index
        collection_type = Collection[model_class]
        try:
            adapter = TypeAdapter(collection_type)
        except Exception:
            # Fallback: fetch raw and parse manually
            raw = self._http_client.get_raw(odata_id)
            members_raw = raw.get("Members", [])
            members = []
            for member_raw in members_raw:
                link_id = member_raw.get("@odata.id")
                if link_id:
                    try:
                        member = self._http_client.get(link_id, model_class)
                        members.append(member)
                    except RedfishException as exc:
                        logger.warning("Failed to fetch member %s: %s, skipping", link_id, exc)
            return members

        raw = self._http_client.get_raw(odata_id)
        collection = adapter.validate_python(raw)

        if not collection.members:
            logger.warning("Collection %s has no members", odata_id)
            return []

        # Step 2: expand each member
        expanded_members = []
        for member in collection.members:
            if not member.odata_id:
                continue
            try:
                full_member = self._http_client.get(member.odata_id, model_class)
                expanded_members.append(full_member)
            except RedfishException as exc:
                logger.warning(
                    "Failed to fetch collection member %s: %s, skipping",
                    member.odata_id, exc
                )

        return expanded_members

    def _get_list(self, links: List[Link], model_class: Type[T]) -> List[T]:
        """
        Fetch a list of resources from a list of Link objects.
        Skips items that fail to fetch (logs warning and continues).
        """
        results = []
        for link in links:
            if not link.odata_id:
                continue
            try:
                item = self._http_client.get(link.odata_id, model_class)
                if item is not None:
                    results.append(item)
            except RedfishException as exc:
                logger.warning("Failed to fetch %s: %s, skipping", link.odata_id, exc)
        return results

    # ------------------------------------------------------------------
    # Cached service accessors (absorbed from RootServiceManager)
    # ------------------------------------------------------------------

    def _get_session_service(self) -> SessionService:
        """Get the SessionService resource."""
        root = self._get_root()
        return self._http_client.get(root.session_service.odata_id, SessionService)

    def _get_account_service(self) -> AccountService:
        """Get the AccountService resource."""
        root = self._get_root()
        return self._http_client.get(root.account_service.odata_id, AccountService)

    def _get_chassis_collection(self) -> List[Chassis]:
        """
        Get the Chassis collection.

        Special handling for Lenovo servers: if the collection endpoint returns
        an error, falls back to fetching /redfish/v1/Chassis/1 directly.
        """
        root = self._get_root()
        try:
            return self._get_collection(root.chassis.odata_id, Chassis)
        except RedfishException as exc:
            logger.warning(
                "Chassis collection endpoint failed (%s), falling back to /redfish/v1/Chassis/1",
                exc
            )
            # Lenovo workaround: /redfish/v1/Chassis returns 500
            chassis = self._http_client.get("/redfish/v1/Chassis/1", Chassis)
            return [chassis]

    def _get_chassis_collection_odata_id(self) -> str:
        """Get the Chassis collection @odata.id from the root service."""
        root = self._get_root()
        return root.chassis.odata_id or "/redfish/v1/Chassis"

    def _get_event_service(self) -> EventService:
        """Get the EventService resource."""
        root = self._get_root()
        return self._http_client.get(root.event_service.odata_id, EventService)

    def _get_managers_collection(self) -> List[Manager]:
        """Get the Managers collection."""
        root = self._get_root()
        return self._get_collection(root.managers.odata_id, Manager)

    def _get_managers_collection_odata_id(self) -> str:
        """Get the Managers collection @odata.id from the root service."""
        root = self._get_root()
        return root.managers.odata_id

    def _get_registries_collection(self) -> List[Registry]:
        """Get the Registries collection."""
        root = self._get_root()
        return self._get_collection(root.registries.odata_id, Registry)

    def _get_registries_collection_odata_id(self) -> str:
        """Get the Registries collection @odata.id from the root service."""
        root = self._get_root()
        return root.registries.odata_id

    def _get_systems_collection(self) -> List[System]:
        """Get the Systems collection."""
        root = self._get_root()
        return self._get_collection(root.systems.odata_id, System)

    def _get_systems_collection_odata_id(self) -> str:
        """Get the Systems collection @odata.id from the root service."""
        root = self._get_root()
        return root.systems.odata_id

    def _get_task_service(self) -> TaskService:
        """Get the TaskService resource."""
        root = self._get_root()
        return self._http_client.get(root.tasks.odata_id, TaskService)

    def _get_update_service(self) -> UpdateService:
        """Get the UpdateService resource."""
        root = self._get_root()
        return self._http_client.get(root.update_service.odata_id, UpdateService)

    # ==================================================================
    # Component query methods — Systems side
    # ==================================================================

    def get_system(self, system_id: Optional[str] = None) -> System:
        """
        Get a single system (physical server) resource.

        If system_id is None and there is exactly one system, returns it
        automatically. If there are multiple systems and no ID is specified,
        raises an exception.

        Args:
            system_id: System ID (e.g., "1"). Auto-selected if only one system exists.

        Returns:
            System object with manufacturer, model, serial_number, power_state, etc.

        Raises:
            RedfishException: If system not found or multiple systems exist without ID
        """
        return self._systems.get(system_id)

    def get_systems(self) -> List[System]:
        """
        Get all system (physical server) resources.

        Returns:
            List of System objects
        """
        return self._get_systems_collection()

    def get_processors(self, system_id: Optional[str] = None) -> List[Processor]:
        """
        Get the list of processors (CPUs) for a system.

        Args:
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            List of Processor objects
        """
        return self._systems.processors(system_id)

    def get_processor(self, processor_id: str, system_id: Optional[str] = None) -> Processor:
        """
        Get a single processor (CPU) by ID.

        Args:
            processor_id: Processor ID (e.g., "1")
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            Processor resource
        """
        system = self._systems.get(system_id)
        return self._http_client.get(
            f"{system.processors.odata_id}/{processor_id}", Processor
        )

    def get_memory(self, system_id: Optional[str] = None) -> List[Memory]:
        """
        Get the list of memory modules (DIMMs) for a system.

        Args:
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            List of Memory objects
        """
        return self._systems.memory(system_id)

    def get_memory_device(self, memory_id: str, system_id: Optional[str] = None) -> Memory:
        """
        Get a single memory module (DIMM) by ID.

        Args:
            memory_id: Memory ID (e.g., "1")
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            Memory resource
        """
        system = self._systems.get(system_id)
        return self._http_client.get(
            f"{system.odata_id}/Memory/{memory_id}", Memory
        )

    def get_storages(self, system_id: Optional[str] = None) -> List:
        """
        Get the list of storage controllers for a system.

        Args:
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            List of Storage objects
        """
        return self._systems.storages(system_id)

    def get_volumes(self, storage_id: str, system_id: Optional[str] = None) -> List:
        """
        Get the list of volumes for a given storage controller.

        Args:
            storage_id: Storage controller ID
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            List of Volume objects
        """
        return self._systems.volumes(storage_id, system_id)

    def get_gpus(self, system_id: Optional[str] = None) -> List:
        """
        Get GPU information for a system.

        Uses multi-vendor fallback strategy:
        1. Try GraphicsControllers (standard path)
        2. Fall back to Chassis PCIeDevices filtered by GPU name
        3. Fall back to System.Links.PCIeDevices

        Args:
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            List of Gpu objects
        """
        return self._systems.gpus(system_id)

    def get_bios(self, system_id: Optional[str] = None) -> Bios:
        """
        Get BIOS information for a system.

        Args:
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            Bios resource
        """
        return self._systems.bios(system_id)

    def get_system_log_services(self, system_id: Optional[str] = None) -> List[Log]:
        """
        Get the list of log services for a system.

        Args:
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            List of Log objects
        """
        return self._systems.log_services(system_id)

    def get_system_log_entries(
        self,
        log_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> List[LogEntry]:
        """
        Get log entries for a system log service.

        Args:
            log_id: Log service ID (e.g., "Log1", "Sel"). Optional
                — when omitted and there is exactly one log service,
                it is auto-selected.
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            List of LogEntry objects (uses ``?$expand=.($levels=1)`` to
            inline members in one HTTP round trip when supported).
        """
        return self._systems.log_entries(log_id, system_id)

    # ------------------------------------------------------------------
    # Log service single resource + ClearLog action
    # ------------------------------------------------------------------

    def get_system_log_service(
        self,
        log_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> Log:
        """
        Get a single LogService resource (includes Actions block such as
        ``#LogService.ClearLog``).

        Differs from :meth:`get_system_log_services` which returns the
        collection members and may omit Actions on some BMCs.

        ``log_id`` is optional (auto-selected when there is exactly one
        log service) and the per-service URL is discovered from the
        LogServices collection rather than built by string concatenation.
        """
        return self._systems.log_service(log_id, system_id)

    def clear_system_log(
        self,
        log_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> None:
        """
        Invoke ``#LogService.ClearLog`` on a system log service.

        Raises :class:`RedfishValidationError` if the BMC does not advertise
        the ClearLog action.
        """
        return self._systems.clear_system_log(log_id, system_id)

    # ------------------------------------------------------------------
    # BootOptions collection
    # ------------------------------------------------------------------

    def get_boot_options(self, system_id: Optional[str] = None) -> List[BootOption]:
        """
        Get the BootOptions collection for a system (modern boot model).

        Returns an empty list when the system does not expose a BootOptions
        link (legacy ``BootSourceOverrideTarget`` only).
        """
        return self._systems.boot_options(system_id)

    def get_boot_option(self, option_id: str, system_id: Optional[str] = None) -> BootOption:
        """Get a single BootOption resource by ID."""
        return self._systems.boot_option(option_id, system_id)

    def set_boot_option_enabled(
        self,
        option_id: str,
        enabled: bool,
        system_id: Optional[str] = None,
    ) -> BootOption:
        """
        Toggle a BootOption's ``BootOptionEnabled`` flag via PATCH and
        return the re-read resource.
        """
        return self._systems.set_boot_option_enabled(option_id, enabled, system_id)

    def get_system_fru(self, system_id: Optional[str] = None) -> Optional[Fru]:
        """
        Get FRU (Field Replaceable Unit) information for a system.

        This is a vendor-specific extension. Returns None if not available.

        Args:
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            Fru object, or None if not available
        """
        return self._systems.fru_info(system_id)

    def get_pcie_device(self, odata_id: str):
        """
        Get a specific PCIe device by its @odata.id.

        Args:
            odata_id: The @odata.id of the PCIe device

        Returns:
            PCIeDevice resource
        """
        return self._systems.pcie_device(odata_id)

    def change_boot_source(
        self,
        target: str,
        system_id: Optional[str] = None,
        mode: str = "UEFI",
        enabled: str = "Once",
    ) -> SystemPatchSetting:
        """
        Change the boot source override target.

        Validates the target against the system's allowable values,
        then sends a PATCH request with the new boot settings.

        Args:
            target: Boot target (e.g., "Pxe", "Hdd", "Cd", "BiosSetup")
            system_id: System ID. Auto-selected if only one system exists.
            mode: Boot source override mode ("UEFI" or "Legacy")
            enabled: Override enable mode ("Once", "Continuous", "Disabled")

        Returns:
            Updated SystemPatchSetting

        Raises:
            RedfishValidationError: If target is not in allowable values
        """
        return self._systems.change_boot_source(target, system_id, mode, enabled)

    def reset(
        self,
        reset_type: str,
        system_id: Optional[str] = None,
        skip_power_state_check: bool = False,
    ):
        """
        Perform a system reset (power on/off/restart).

        Validates that the requested reset type is compatible with the current
        power state before sending the request.

        Args:
            reset_type: Reset type string (e.g., "GracefulRestart", "ForceOff", "On")
            system_id: System ID. Auto-selected if only one system exists.
            skip_power_state_check: Skip power state compatibility check

        Returns:
            RedfishResponse

        Raises:
            RedfishValidationError: If reset_type is incompatible with current power state
        """
        return self._systems.reset(reset_type, system_id, skip_power_state_check)

    # ==================================================================
    # Component query methods — Chassis side
    # ==================================================================

    def get_chassis(self, chassis_id: str = "1") -> Chassis:
        """
        Get chassis (physical enclosure) information.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            Chassis resource with manufacturer, model, serial number, etc.
        """
        return self._chassis.get(chassis_id)

    def get_drives(self, chassis_id: str = "1") -> List:
        """
        Get the list of physical drives (HDD/SSD/NVMe) in a chassis.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            List of Drive objects
        """
        return self._chassis.drives(chassis_id)

    # ------------------------------------------------------------------
    # Drive single-resource + Drive.Reset action
    # ------------------------------------------------------------------

    def get_drive(self, odata_id: str) -> Drive:
        """
        Get a single Drive resource directly by its ``@odata.id``.

        Useful when a Storage controller only exposes Link references and the
        caller needs the full Drive detail.
        """
        return self._systems.drive_by_odata_id(odata_id)

    def drive_reset(self, drive_odata_id: str, reset_type: str) -> None:
        """
        Invoke ``#Drive.Reset`` on a drive (NVMe power cycle, etc.).

        See :meth:`SystemsManager.drive_reset` for behaviour.
        """
        return self._systems.drive_reset(drive_odata_id, reset_type)

    # ------------------------------------------------------------------
    # IndicatorLED writes
    # ------------------------------------------------------------------

    def set_indicator_led(self, state: str, chassis_id: str = "1") -> str:
        """
        Set ``Chassis.IndicatorLED``. ``state`` must be one of
        ``Lit`` / ``Blinking`` / ``Off``.
        """
        return self._chassis.set_indicator_led(state, chassis_id)

    def set_drive_indicator_led(self, drive_odata_id: str, state: str) -> str:
        """
        Set ``Drive.IndicatorLED`` on a specific drive. ``state`` must be one
        of ``Lit`` / ``Blinking`` / ``Off``.
        """
        return self._chassis.set_drive_indicator_led(drive_odata_id, state)

    def get_network_adapters(self, chassis_id: str = "1") -> List:
        """
        Get the list of network adapters (NICs) in a chassis.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            List of NetworkAdapter objects
        """
        return self._chassis.network_adapters(chassis_id)

    def get_pcie_devices(self, chassis_id: str = "1") -> List:
        """
        Get the list of PCIe devices in a chassis.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            List of PCIeDevice objects
        """
        return self._chassis.pcie_devices(chassis_id)

    def get_power(self, chassis_id: str = "1") -> Power:
        """
        Get power information (PSUs, power controls, voltages) for a chassis.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            Power resource
        """
        return self._chassis.power(chassis_id)

    def get_thermal(self, chassis_id: str = "1") -> Thermal:
        """
        Get thermal information (fans, temperatures) for a chassis.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            Thermal resource
        """
        return self._chassis.thermal(chassis_id)

    def get_inlet_history_temperature(
        self, chassis_id: str = "1"
    ) -> Optional[InletHistoryTemperature]:
        """
        Get air inlet historical temperature samples for a chassis.

        Wraps ``ChassisManager.inlet_history_temperature``. The method first
        resolves the sub-resource URL via ``get_thermal()`` (Redfish link
        discovery), then GETs the InletHistoryTemperature resource.

        Returns ``None`` when the BMC does not advertise the sub-resource or
        returns 404; other errors (auth/network/parse) propagate.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            InletHistoryTemperature model, or None when not supported.
        """
        return self._chassis.inlet_history_temperature(chassis_id)

    def get_fru_service(self, chassis_id: str = "1") -> List[dict]:
        """
        Get FRU service data from the chassis OEM extension.

        This is a vendor-specific feature (e.g., Huawei/xFusion iBMC).

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            List of raw FRU service data dicts
        """
        return self._chassis.fru_service(chassis_id)

    # ==================================================================
    # Component query methods — Managers (BMC) side
    # ==================================================================

    def get_manager(self, manager_id: str = "1") -> Manager:
        """
        Get BMC manager information.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            Manager resource with firmware_version, model, etc.
        """
        return self._managers.get(manager_id)

    def get_manager_log_services(self, manager_id: str = "1") -> List[Log]:
        """
        Get the list of log services for a BMC manager.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            List of Log objects
        """
        return self._managers.log_services(manager_id)

    def get_manager_log_entries(
        self,
        log_id: Optional[str] = None,
        manager_id: str = "1",
    ) -> List[LogEntry]:
        """
        Get log entries for a BMC manager log service.

        Args:
            log_id: Log service ID (e.g., "Sel", "OperateLog"). Optional
                — when omitted and there is exactly one log
                service, it is auto-selected.
            manager_id: Manager ID (default "1")

        Returns:
            List of LogEntry objects (uses ``?$expand=.($levels=1)`` to
            inline members in one HTTP round trip when supported).
        """
        return self._managers.log_entries(log_id, manager_id)

    def get_network_protocol(self, manager_id: str = "1") -> NetworkProtocol:
        """
        Get network protocol configuration for a BMC manager.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            NetworkProtocol resource
        """
        return self._managers.network_protocol(manager_id)

    def get_manager_ethernet_interfaces(self, manager_id: str = "1") -> List[EthernetInterface]:
        """
        Get the list of Ethernet interfaces for a BMC manager.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            List of EthernetInterface objects
        """
        return self._managers.ethernet_interfaces(manager_id)

    def get_host_interfaces(self, manager_id: str = "1") -> List[HostInterface]:
        """
        Get the list of host interfaces for a BMC manager.

        Args:
            manager_id: Manager ID (default "1")

        Returns:
            List of HostInterface objects
        """
        return self._managers.host_interfaces(manager_id)

    # ==================================================================
    # Component query methods — Account service
    # ==================================================================

    def get_accounts(self) -> List[Account]:
        """
        Get all user accounts.

        Returns:
            List of Account objects
        """
        return self._accounts.accounts()

    def get_roles(self) -> List[Role]:
        """
        Get all user roles.

        Returns:
            List of Role objects
        """
        return self._accounts.roles()

    def add_account(self, account: Account) -> Account:
        """
        Create a new user account.

        Args:
            account: Account model with UserName, Password, RoleId, Enabled fields

        Returns:
            Created Account resource
        """
        return self._accounts.add(account)

    def update_account(self, username: str, account: Account) -> Account:
        """
        Update an existing user account.

        Args:
            username: Username of the account to update
            account: Account model with fields to update

        Returns:
            Updated Account resource
        """
        return self._accounts.update(username, account)

    def delete_account(self, username: str) -> str:
        """
        Delete a user account.

        Args:
            username: Username of the account to delete

        Returns:
            Response body (usually empty)
        """
        return self._accounts.delete(username)

    # ==================================================================
    # Component query methods — Session service
    # ==================================================================

    def get_sessions(self) -> List[Session]:
        """
        Get all active sessions.

        Returns:
            List of Session objects
        """
        return self._sessions.sessions()

    def get_session(self, session_id: str) -> Session:
        """
        Get a specific session by ID.

        Args:
            session_id: Session ID

        Returns:
            Session resource
        """
        return self._sessions.get(session_id)

    def create_session(
        self,
        username: str,
        password: str,
        switch_to_token_auth: bool = False,
    ) -> Session:
        """
        Create a new session (login to the BMC).

        After creation, the X-Auth-Token is returned in the response header.
        If switch_to_token_auth=True, the SDK client will use this token
        for subsequent requests instead of Basic Auth.

        Args:
            username: BMC username
            password: BMC password
            switch_to_token_auth: If True, switch client to token-based auth

        Returns:
            Session resource with x_auth_token populated
        """
        return self._sessions.create(username, password, switch_to_token_auth)

    def delete_session(self, session_id: str) -> str:
        """
        Delete a session (logout).

        Args:
            session_id: Session ID to delete

        Returns:
            Response body (usually empty)
        """
        return self._sessions.delete(session_id)

    # ==================================================================
    # Component query methods — Event service
    # ==================================================================

    def get_subscriptions(self) -> List[Subscription]:
        """
        Get all event subscriptions (collection-expanded).

        Internally lists the ``Subscriptions`` collection and fetches each
        member by its ``@odata.id``; members that fail to fetch are skipped
        with a warning.

        Returns:
            List of Subscription objects
        """
        return self._events.subscriptions()

    def get_subscription(self, id_or_uri: str) -> Subscription:
        """
        Get a single event subscription by Id or full ``@odata.id``.

        Args:
            id_or_uri: Either a bare subscription Id (e.g. ``"1"``) or the
                full ``@odata.id`` path
                (e.g. ``"/redfish/v1/EventService/Subscriptions/1"``).

        Returns:
            The Subscription resource.
        """
        return self._events.get_subscription(id_or_uri)

    def subscribe(
        self,
        destination: str,
        event_types: Optional[List[str]] = None,
        context: Optional[str] = None,
        *,
        protocol: str = "Redfish",
        http_headers: Optional[Any] = None,
        origin_resources: Optional[List[Dict[str, Any]]] = None,
        subscription_type: Optional[str] = None,
        registry_prefixes: Optional[List[str]] = None,
        resource_types: Optional[List[str]] = None,
        message_ids: Optional[List[str]] = None,
        delivery_retry_policy: Optional[str] = None,
        event_format_type: Optional[str] = None,
        severities: Optional[List[str]] = None,
        oem_subscription_type: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        raw_body: Optional[Dict[str, Any]] = None,
    ) -> Subscription:
        """
        Create a new event subscription (webhook).

        Every Redfish ``EventDestination`` field observed in the wild is
        exposed as a keyword-only argument, and ``extra`` / ``raw_body``
        provide an escape hatch for OEM-specific payloads. The SDK does
        **not** apply any vendor-default values — callers wishing to support
        multiple BMC vendors may try several payload shapes in sequence
        (catching :class:`RedfishException` between attempts).

        Args:
            destination: URL to receive events (e.g. ``"https://my-server/events"``).
            event_types: Optional list of event types (e.g. ``["Alert"]``).
            context: Optional context string identifying the subscription.
            protocol: Wire protocol; defaults to ``"Redfish"``.
            http_headers: Optional headers to send on the callback POST.
                Pass either a ``dict`` or a ``list[dict]`` — both forms are
                commonly seen across BMC vendors.
            origin_resources: Optional list of ``{"@odata.id": "..."}``.
            subscription_type: Optional ``SubscriptionType`` value.
            registry_prefixes: Optional message-registry filter list.
            resource_types: Optional list of resource-type filters.
            message_ids: Optional list of message Ids to filter on.
            delivery_retry_policy: Optional retry policy.
            event_format_type: Optional event format type.
            severities: Optional severity filter list.
            oem_subscription_type: Optional vendor-specific subscription type.
            extra: Optional dict shallow-merged into the request body.
            raw_body: If provided, replaces the entire auto-generated body.

        Returns:
            The created Subscription resource (as echoed by the BMC).
        """
        return self._events.subscribe(
            destination,
            event_types,
            context,
            protocol=protocol,
            http_headers=http_headers,
            origin_resources=origin_resources,
            subscription_type=subscription_type,
            registry_prefixes=registry_prefixes,
            resource_types=resource_types,
            message_ids=message_ids,
            delivery_retry_policy=delivery_retry_policy,
            event_format_type=event_format_type,
            severities=severities,
            oem_subscription_type=oem_subscription_type,
            extra=extra,
            raw_body=raw_body,
        )

    def delete_subscription(self, id_or_uri: str) -> str:
        """
        Delete an event subscription.

        Args:
            id_or_uri: Either a bare subscription Id (e.g. ``"1"``) or the
                full ``@odata.id`` path
                (e.g. ``"/redfish/v1/EventService/Subscriptions/1"``).

        Returns:
            Raw response body (typically empty on 204).
        """
        return self._events.delete(id_or_uri)

    # ------------------------------------------------------------------
    # Event service — extra accessors
    # ------------------------------------------------------------------

    def get_event_service(self) -> EventService:
        """
        Get the full EventService resource (includes Actions block).

        Use this when you need ``event_service.actions`` (e.g. to discover
        the SubmitTestEvent target or its AllowableValues).
        """
        return self._events.service()

    def submit_test_event(
        self,
        event_type: str,
        message: Optional[str] = None,
        message_id: Optional[str] = None,
        severity: Optional[str] = None,
        message_args: Optional[List[str]] = None,
    ) -> None:
        """
        Invoke ``#EventService.SubmitTestEvent`` on the BMC.

        See :meth:`EventServiceManager.submit_test_event` for details.
        """
        return self._events.submit_test_event(
            event_type, message, message_id, severity, message_args
        )

    # ==================================================================
    # Component query methods — Update service
    # ==================================================================

    def get_firmware_inventory(self) -> List[FirmwareInventory]:
        """
        Get the list of firmware inventory entries.

        Returns all firmware/software component versions installed on the system
        (BIOS, BMC, CPLD, NIC firmware, etc.).

        Returns:
            List of FirmwareInventory objects
        """
        return self._updates.firmware_inventory()

    def get_client_certificates(self) -> List[ClientCertificate]:
        """
        Get the list of client certificates for firmware update authentication.

        Returns:
            List of ClientCertificate objects
        """
        return self._updates.client_certificates()

    def simple_update(
        self,
        image_uri: str,
        transfer_protocol: str = "HTTP",
        targets: Optional[list] = None,
        vendor: Optional[str] = None,
        **kwargs,
    ) -> RedfishResponse:
        """
        Trigger a firmware update via a remote image URI (e.g., NFS, HTTP).

        Automatically detects the server vendor and uses the appropriate
        request body format. The vendor can be manually overridden.

        Args:
            image_uri: URI of the firmware image (e.g., "http://nas/fw/bmc.bin")
            transfer_protocol: Transfer protocol (e.g., "HTTP", "NFS", "TFTP")
            targets: Optional list of firmware target paths
            vendor: Optional vendor override (e.g., "inspur", "lenovo").
                    If not set, the vendor is auto-detected.
            **kwargs: Vendor-specific parameters (e.g., preserve_config,
                      username, password, flash_item, etc.)

        Returns:
            RedfishResponse (may contain a task reference for async update)
        """
        return self._updates.simple_update(
            image_uri, transfer_protocol, targets, vendor, **kwargs
        )

    # ==================================================================
    # Component query methods — Registries
    # ==================================================================

    def get_registries(self) -> List[Registry]:
        """
        Get the list of message registries.

        Returns:
            List of Registry objects
        """
        return self._registries.registries()

    def get_registry(self, registry_id: str) -> Registry:
        """
        Get a specific message registry by ID.

        Args:
            registry_id: Registry ID (e.g., "Base.1.15.0")

        Returns:
            Registry resource
        """
        return self._registries.get(registry_id)

    # ==================================================================
    # Component query methods — Tasks
    # ==================================================================

    def get_tasks(self) -> List[Task]:
        """
        Get the list of all tasks.

        Returns:
            List of Task objects
        """
        return self._tasks.tasks()

    def get_task(self, task_id: str) -> Task:
        """
        Get a specific task by ID.

        Args:
            task_id: Task ID

        Returns:
            Task resource
        """
        return self._tasks.get(task_id)

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: int = 5,
        timeout: int = 600,
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
        return self._tasks.wait_for_task(task_id, poll_interval, timeout)

    # ==================================================================
    # Component query methods — Firmware / FRU
    # ==================================================================

    def get_baseboard_fru(self, chassis_id: str = "1") -> Optional[dict]:
        """
        Get baseboard (motherboard) FRU data.

        Uses the Chassis OEM FRU service to retrieve FRU board info.
        This is a vendor-specific extension (e.g., Huawei/xFusion iBMC).

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            Raw FRU board data dict, or None if not available
        """
        return self._chassis.fru_service_board(chassis_id)

    def get_mainboard(
        self,
        system_id: Optional[str] = None,
        chassis_id: str = "1",
    ) -> Optional[MainBoard]:
        """
        Get mainboard (motherboard) information with multi-path fallback.

        Fallback order:
        1. System FRU board info
        2. Chassis OEM FRU service board info
        3. Chassis OEM mainboard field

        Args:
            system_id: System ID. Auto-selected if only one system exists.
            chassis_id: Chassis ID (default "1")

        Returns:
            MainBoard model, or None if not available from any supported source
        """
        try:
            system_fru = self.get_system_fru(system_id)
            if system_fru is not None and system_fru.board is not None:
                logger.debug("Mainboard found via system FRU")
                return system_fru.board
        except RedfishException as exc:
            logger.debug("Failed to get mainboard via system FRU: %s", exc)

        try:
            board_raw = self.get_baseboard_fru(chassis_id)
            if board_raw:
                if "BoardInfo" in board_raw:
                    mainboard_raw = board_raw["BoardInfo"]
                    mainboard_raw["@odata.type"] = board_raw.get("@odata.type", "#MainBoard.v1_0_0.MainBoard")
                    mainboard_raw["@odata.id"] = board_raw.get("@odata.id")
                    mainboard_raw["@odata.context"] = board_raw.get("@odata.context")
                    logger.debug("Mainboard found via chassis FRU service")
                    return MainBoard.model_validate(mainboard_raw)
                return MainBoard.model_validate(board_raw)
        except RedfishException as exc:
            logger.debug("Failed to get mainboard via chassis FRU service: %s", exc)
        except Exception as exc:
            logger.warning("Failed to parse mainboard from chassis FRU service: %s", exc)

        try:
            chassis = self.get_chassis(chassis_id)
            if chassis.oem and chassis.oem.bmc and chassis.oem.bmc.mainboard:
                logger.debug("Mainboard found via chassis OEM mainboard")
                return chassis.oem.bmc.mainboard
        except RedfishException as exc:
            logger.debug("Failed to get mainboard via chassis OEM data: %s", exc)

        logger.debug("Mainboard not available from any supported source")
        return None

    # ------------------------------------------------------------------
    # Component query methods — Extracted sub-resources
    # ------------------------------------------------------------------

    def get_fan(self, chassis_id: str = "1") -> List[Fan]:
        """
        Get fan information with multi-path fallback.

        Fallback order:
        1. ``/redfish/v1/Chassis/{id}/ThermalSubsystem/Fans`` — newer Redfish schema,
           fetches the collection then GETs each member individually.
        2. ``/redfish/v1/Chassis/{id}/Thermal`` — legacy schema,
           extracts the ``Fans`` array from the Thermal resource.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            List of Fan objects (empty list if not available from any supported path)
        """
        # Path 1: ThermalSubsystem/Fans (newer Redfish schema)
        try:
            subsystem_path = f"/redfish/v1/Chassis/{chassis_id}/ThermalSubsystem/Fans"
            collection = self.get_raw(subsystem_path)
            if collection is not None:
                members = collection.get("Members", [])
                fans: List[Fan] = []
                for member in members:
                    odata_id = member.get("@odata.id")
                    if odata_id:
                        try:
                            fan_raw = self.get_raw(odata_id)
                            fans.append(Fan.model_validate(fan_raw))
                        except Exception as exc:
                            logger.debug("Failed to fetch fan member %s: %s", odata_id, exc)
                if fans:
                    logger.debug("Fans found via %s (%d fans)", subsystem_path, len(fans))
                    return fans
        except RedfishException as exc:
            logger.debug("Failed to get fans via ThermalSubsystem: %s", exc)

        # Path 2: Thermal (legacy schema)
        try:
            thermal = self.get_thermal(chassis_id)
            if thermal.fans:
                logger.debug("Fans found via Thermal resource (%d fans)", len(thermal.fans))
                return thermal.fans
        except RedfishException as exc:
            logger.debug("Failed to get fans via Thermal: %s", exc)

        logger.debug("Fan info not available from any supported source")
        return []

    def get_power_supplies(self, chassis_id: str = "1") -> List[PowerSupply]:
        """
        Get the list of power supply units (PSUs) for a chassis.

        Extracts the PowerSupplies array from the Power resource.

        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            List of PowerSupply objects (empty list if no PSUs found)
        """
        power = self.get_power(chassis_id)
        return power.power_supplies or []

    # ------------------------------------------------------------------
    # Component query methods — System-level convenience
    # ------------------------------------------------------------------

    def get_manufacturer(self, system_id: Optional[str] = None) -> str:
        """
        Get the server manufacturer name.

        Args:
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            Manufacturer name string (e.g., "Huawei", "Inspur", "H3C", "Lenovo")

        Raises:
            RedfishException: If manufacturer field is not available
        """
        system = self._systems.get(system_id)
        if not system.manufacturer:
            raise RedfishException(500, "Manufacturer field not found in system resource")
        return system.manufacturer

    # ------------------------------------------------------------------
    # Resource metadata methods (ETag / @odata.id)
    # ------------------------------------------------------------------

    def get_etag(self, path: str) -> Optional[str]:
        """
        Get the cached ETag for a Redfish resource path.

        ETag is used for concurrency control in Redfish:
        - GET responses include an ETag header (or @odata.etag in JSON body)
        - PATCH/PUT requests should include If-Match header with the ETag
        - This prevents "lost update" problems when multiple clients modify the same resource

        If the resource has not been fetched yet (no cached ETag), this method
        will perform a HEAD-like GET to retrieve and cache the ETag.

        Args:
            path: Redfish resource path (e.g., "/redfish/v1/Systems/1")

        Returns:
            ETag string (e.g., '"W/12345"'), or None if the server does not provide ETags
        """
        # Check cached ETag first
        cached = self._http_client._last_etag.get(path)
        if cached:
            return cached

        # Fetch the resource to populate the ETag cache
        try:
            self._http_client.get_raw(path)
        except RedfishException:
            return None

        return self._http_client._last_etag.get(path)

    def get_odata_id(self, key: RedfishResource) -> Optional[str]:
        """
        Look up the @odata.id for a Redfish resource by its ``RedfishResource`` key.

        Automatically searches the Redfish resource tree in a fixed order:

        1. RootService (``/redfish/v1/``)
        2. First member of the Systems collection
        3. First member of the Chassis collection
        4. First member of the Managers collection

        The first match wins and is returned immediately.

        Args:
            key: A ``RedfishResource`` enum member identifying the resource
                 (e.g., ``RedfishResource.PROCESSORS``, ``RedfishResource.THERMAL``)

        Returns:
            The @odata.id string (e.g., ``"/redfish/v1/Systems/1/Processors"``),
            or ``None`` if the key was not found in any layer.

        Example::

            from redfish_sdk import RedfishClient, RedfishResource

            client = RedfishClient(host="10.0.0.1", username="admin", password="pwd")
            url = client.get_odata_id(RedfishResource.PROCESSORS)
            # → "/redfish/v1/Systems/1/Processors"
        """
        field_name = key.value  # e.g. "Processors", "Thermal"

        # Step 1: Search in RootService
        try:
            root_data = self._http_client.get_raw("/redfish/v1/")
            result = self._extract_odata_id(root_data, field_name)
            if result is not None:
                return result
        except Exception as exc:
            logger.warning("get_odata_id: failed to fetch RootService: %s", exc)

        # Step 2–4: Search in first member of Systems, Chassis, Managers
        collection_keys = ["Systems", "Chassis", "Managers"]
        for col_key in collection_keys:
            try:
                first_member_data = self._get_first_collection_member_raw(col_key)
                if first_member_data is None:
                    continue
                result = self._extract_odata_id(first_member_data, field_name)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning(
                    "get_odata_id: failed to search in %s collection: %s",
                    col_key, exc,
                )

        return None

    @staticmethod
    def get_resource_odata_id(resource) -> Optional[str]:
        """
        Extract the @odata.id from a Redfish resource object.

        This is a backward-compatible convenience method that works with any
        SDK model object (Entity, Link, or any pydantic model with an odata_id field).

        Args:
            resource: Any Redfish resource model instance (e.g., System, Chassis, Processor)

        Returns:
            The @odata.id string (e.g., "/redfish/v1/Systems/1"), or None if not present
        """
        return getattr(resource, "odata_id", None)

    # ------------------------------------------------------------------
    # get_odata_id internal helpers
    # ------------------------------------------------------------------

    def _get_first_collection_member_raw(self, collection_key: str) -> Optional[dict]:
        """
        Fetch the raw JSON of the first member in a top-level collection.

        Args:
            collection_key: Top-level collection name (e.g., "Systems", "Chassis", "Managers")

        Returns:
            Raw JSON dict of the first member, or None if not available
        """
        # Get collection @odata.id from root
        root_data = self._http_client.get_raw("/redfish/v1/")
        col_ref = root_data.get(collection_key)
        if col_ref is None:
            return None

        col_odata_id = col_ref.get("@odata.id") if isinstance(col_ref, dict) else None
        if not col_odata_id:
            return None

        # Get collection members list
        col_data = self._http_client.get_raw(col_odata_id)
        members = col_data.get("Members", [])
        if not members:
            return None

        # Get first member
        first_member_id = members[0].get("@odata.id")
        if not first_member_id:
            return None

        return self._http_client.get_raw(first_member_id)

    @staticmethod
    def _extract_odata_id(data: dict, field_name: str) -> Optional[str]:
        """
        Extract @odata.id for a given field name from a resource JSON dict.

        Search order:
        1. Top-level fields
        2. Links section
        3. Oem section (recursive)

        Args:
            data: Raw JSON dict of a Redfish resource
            field_name: The field name to look for (e.g., "Processors", "Thermal")

        Returns:
            The @odata.id string, or None if not found
        """
        # 1. Top-level field
        value = data.get(field_name)
        if value is not None:
            odata_id = RedfishClient._resolve_odata_id(value)
            if odata_id:
                return odata_id

        # 2. Links section
        links = data.get("Links")
        if isinstance(links, dict):
            value = links.get(field_name)
            if value is not None:
                odata_id = RedfishClient._resolve_odata_id(value)
                if odata_id:
                    return odata_id

        # 3. Oem section (recursive search)
        oem = data.get("Oem")
        if isinstance(oem, dict):
            odata_id = RedfishClient._search_oem_for_key(oem, field_name)
            if odata_id:
                return odata_id

        return None

    @staticmethod
    def _resolve_odata_id(value) -> Optional[str]:
        """
        Resolve @odata.id from a field value.

        Handles:
        - dict with "@odata.id" key
        - str (direct path)
        - list of dicts (takes first element's @odata.id)
        """
        if isinstance(value, dict):
            return value.get("@odata.id")
        if isinstance(value, str) and value.startswith("/"):
            return value
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                return first.get("@odata.id")
        return None

    @staticmethod
    def _search_oem_for_key(oem_data: dict, field_name: str) -> Optional[str]:
        """
        Recursively search the Oem section for a field matching field_name.
        """
        for k, v in oem_data.items():
            if k == field_name:
                return RedfishClient._resolve_odata_id(v)
            if isinstance(v, dict):
                result = RedfishClient._search_oem_for_key(v, field_name)
                if result:
                    return result
        return None

    # ------------------------------------------------------------------
    # Raw JSON access (generic CRUD)
    # ------------------------------------------------------------------

    def get_raw(self, odata_id: str) -> dict:
        """
        Fetch the raw JSON data for any Redfish resource by its @odata.id.

        Unlike typed getter methods (e.g., ``get_system()``), this returns the
        unprocessed JSON dict exactly as the BMC returns it — useful for
        inspecting vendor-specific (OEM) fields, debugging, or accessing
        resources that the SDK does not yet model.

        Args:
            odata_id: The @odata.id path of the resource
                      (e.g., ``"/redfish/v1/Systems/1"``)

        Returns:
            Raw JSON dict of the resource

        Raises:
            RedfishException: On HTTP errors (404, 500, etc.)

        Example::

            from redfish_sdk import RedfishClient

            client = RedfishClient(host="10.0.0.1", username="admin", password="pwd")
            data = client.get_raw("/redfish/v1/Systems/1")
            print(data["Manufacturer"])
            # → "Huawei"
        """
        return self._http_client.get_raw(odata_id)

    def patch(self, odata_id: str, body: dict) -> dict:
        """
        Send a PATCH request to partially update a Redfish resource.

        Automatically handles ETag-based concurrency control:
        if no ETag is cached for the target path, a GET is issued first
        to obtain one. The ETag is then sent as the ``If-Match`` header.

        Args:
            odata_id: The @odata.id path of the resource to update
                      (e.g., ``"/redfish/v1/Systems/1"``)
            body: A dict containing only the fields to modify

        Returns:
            Raw JSON dict of the BMC response (empty dict ``{}`` on 204 No Content)

        Raises:
            RedfishException: On HTTP errors (412 Precondition Failed, 500, etc.)

        Example::

            client.patch("/redfish/v1/Systems/1", {
                "Boot": {
                    "BootSourceOverrideEnabled": "Once",
                    "BootSourceOverrideTarget": "Pxe",
                }
            })
        """
        # Ensure ETag is cached before PATCH (auto-GET if missing)
        if odata_id not in self._http_client._last_etag:
            try:
                self._http_client.get_raw(odata_id)
            except RedfishException:
                pass  # proceed with '*' wildcard if GET fails

        response = self._http_client.patch_raw(odata_id, body)

        if response.status_code == 204 or not response.text.strip():
            return {}
        return response.json()

    def post(self, odata_id: str, body: Optional[dict] = None) -> dict:
        """
        Send a POST request to create a resource or trigger an action.

        Args:
            odata_id: The target path
                      (e.g., ``"/redfish/v1/AccountService/Accounts"`` or
                      ``"/redfish/v1/Systems/1/Actions/ComputerSystem.Reset"``)
            body: Optional request body dict

        Returns:
            Raw JSON dict of the BMC response (empty dict ``{}`` on 204 No Content)

        Raises:
            RedfishException: On HTTP errors (400, 500, etc.)

        Example::

            # Trigger a system reset
            client.post(
                "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset",
                {"ResetType": "GracefulRestart"},
            )

            # Create a user account
            client.post("/redfish/v1/AccountService/Accounts", {
                "UserName": "operator",
                "Password": "Op3r@tor!",
                "RoleId": "Operator",
            })
        """
        response = self._http_client.post_raw(odata_id, body)

        if response.status_code == 204 or not response.text.strip():
            return {}
        return response.json()

    def delete(self, odata_id: str) -> None:
        """
        Send a DELETE request to remove a Redfish resource.

        Args:
            odata_id: The @odata.id path of the resource to delete
                      (e.g., ``"/redfish/v1/SessionService/Sessions/abc123"``)

        Returns:
            None

        Raises:
            RedfishException: On HTTP errors (404, 500, etc.)

        Example::

            client.delete("/redfish/v1/SessionService/Sessions/abc123")
        """
        self._http_client.delete(odata_id)

    # ------------------------------------------------------------------
    # Convenience aggregation method
    # ------------------------------------------------------------------

    def get_all_components_summary(
        self, system_id: Optional[str] = None, chassis_id: str = "1"
    ) -> dict:
        """
        Get a summary of all hardware components in a single call.

        Args:
            system_id: System ID. Auto-selected if only one system exists.
            chassis_id: Chassis ID (default "1")

        Returns:
            Dictionary with all component lists/resources::

                {
                    "processors": List[Processor],
                    "memory": List[Memory],
                    "storages": List[Storage],
                    "gpus": List[Gpu],
                    "drives": List[Drive],
                    "network_adapters": List[NetworkAdapter],
                    "pcie_devices": List[PCIeDevice],
                    "power": Power,
                    "thermal": Thermal,
                    "fans": List[Fan],
                    "power_supplies": List[PowerSupply],
                    "firmware_inventory": List[FirmwareInventory],
                }
        """
        return {
            "processors": self.get_processors(system_id),
            "memory": self.get_memory(system_id),
            "storages": self.get_storages(system_id),
            "gpus": self.get_gpus(system_id),
            "drives": self.get_drives(chassis_id),
            "network_adapters": self.get_network_adapters(chassis_id),
            "pcie_devices": self.get_pcie_devices(chassis_id),
            "power": self.get_power(chassis_id),
            "thermal": self.get_thermal(chassis_id),
            "fans": self.get_fan(chassis_id),
            "power_supplies": self.get_power_supplies(chassis_id),
            "firmware_inventory": self.get_firmware_inventory(),
        }
