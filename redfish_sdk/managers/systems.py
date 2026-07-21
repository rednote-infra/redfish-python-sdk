"""
Systems manager — manages server system resources.

Provides access to:
- System info (power state, model, serial number, etc.)
- Processors (CPUs)
- Memory (DIMMs)
- Storage (controllers + drives + volumes)
- GPUs (via GraphicsControllers or PCIeDevices fallback)
- BIOS settings
- Log services and log entries
- FRU information
- Boot source control
- System reset (power on/off/restart)

"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from ..exceptions import RedfishException, RedfishValidationError
from ..models.chassis import PCIeDevice
from ..models.drive import Drive
from ..models.fru import Fru
from ..models.logs import Log, LogEntry
from ..models.systems import (
    Bios,
    BootOption,
    BootSetting,
    Gpu,
    GpuOEM,
    Memory,
    Processor,
    Storage,
    System,
    SystemPatchSetting,
    Volume,
)

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)

# Boot source override constants
BOOT_OVERRIDE_ENABLED_ONCE = "Once"
BOOT_OVERRIDE_MODE_UEFI = "UEFI"

# PowerState values
_ON_STATES = {"On", "PoweringOn"}
_OFF_STATES = {"Off", "PoweringOff"}

# ResetType -> valid PowerState mapping
_RESET_ALLOWED = {
    "On": _OFF_STATES,            # Can only turn On when currently Off
    "ForceOff": _ON_STATES,       # Can only force off when currently On
    "GracefulShutdown": _ON_STATES,
    "GracefulRestart": _ON_STATES,
    "ForceRestart": _ON_STATES,
    "Nmi": _ON_STATES,
    "ForceOn": _OFF_STATES,
    "PushPowerButton": {"On", "Off", "PoweringOn", "PoweringOff"},
}


class SystemsManager:
    """
    Manages Redfish System resources.


    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def get(self, system_id: Optional[str] = None) -> System:
        """
        Get a system resource.

        If system_id is None and there is exactly one system, returns it automatically.
        If system_id is None and there are multiple systems, raises an error.



        Args:
            system_id: System ID (e.g., "1"). If None, auto-selects the sole system.

        Returns:
            System resource

        Raises:
            RedfishException: If system not found or ambiguous
        """
        if system_id is None:
            systems = self._client._get_systems_collection()
            if not systems:
                raise RedfishException(404, "No system found")
            if len(systems) > 1:
                raise RedfishValidationError(
                    f"Multiple systems found, please specify system_id. "
                    f"Available: {[m.id for m in systems]}"
                )
            return systems[0]

        systems_odata_id = self._client._get_systems_collection_odata_id()
        return self._http.get(
            f"{systems_odata_id}/{system_id}", System
        )

    def processors(self, system_id: Optional[str] = None) -> List[Processor]:
        """
        Get the list of processors (CPUs) for a system.


        """
        system = self.get(system_id)
        return self._client._get_collection(system.processors.odata_id, Processor)

    def memory(self, system_id: Optional[str] = None) -> List[Memory]:
        """
        Get the list of memory modules (DIMMs) for a system.


        """
        system = self.get(system_id)
        return self._client._get_collection(system.odata_id + "/Memory", Memory)

    def storages(self, system_id: Optional[str] = None) -> List[Storage]:
        """
        Get the list of storage controllers for a system.


        """
        system = self.get(system_id)
        return self._client._get_collection(system.storage.odata_id, Storage)

    def volumes(self, storage_id: str, system_id: Optional[str] = None) -> List[Volume]:
        """
        Get the list of volumes for a given storage controller.


        """
        system = self.get(system_id)
        path = f"{system.storage.odata_id}/{storage_id}/Volumes"
        return self._client._get_collection(path, Volume)

    def bios(self, system_id: Optional[str] = None) -> Bios:
        """
        Get BIOS information for a system.


        """
        system = self.get(system_id)
        return self._http.get(f"{system.odata_id}/Bios", Bios)

    def log_services(self, system_id: Optional[str] = None) -> List[Log]:
        """
        Get the list of log services for a system.


        """
        from ._log_helpers import require_log_services_link

        system = self.get(system_id)
        odata_id = require_log_services_link(system, f"System {system.id!r}")
        return self._client._get_collection(odata_id, Log)

    def log_entries(
        self,
        log_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> List[LogEntry]:
        """
        Get log entries for a system log service.

        ``log_id`` is optional. When omitted and there is exactly one
        log service on the system, it is auto-selected. Multiple services
        raise :class:`RedfishValidationError` listing the available IDs.

        The Entries URL is discovered from ``Log.entries.odata_id`` rather
        than hard-coded as ``f"{log_services}/{log_id}/Entries"``.
        """
        from ._log_helpers import (
            fetch_log_entries,
            require_log_services_link,
            resolve_log_service,
        )

        system = self.get(system_id)
        odata_id = require_log_services_link(system, f"System {system.id!r}")
        log = resolve_log_service(self._client, odata_id, log_id)
        return fetch_log_entries(self._client, log)

    # ------------------------------------------------------------------
    # Log service single-resource access + ClearLog action
    # ------------------------------------------------------------------

    def log_service(
        self,
        log_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> Log:
        """
        Get a single LogService resource (includes the Actions block).

        Use this when you need ``Log.actions`` (e.g. to read the ClearLog
        target); ``log_services()`` only returns collection members which
        may omit Actions on some BMCs.

        ``log_id`` is optional; auto-selected when there is exactly
        one log service. The single LogService URL is **discovered dynamically**
        from the ``LogServices`` collection members rather than built by string
        concatenation. Vendors that publish a non-standard child path
        (e.g. ``.../LogServices/SystemEventLog`` instead of ``.../Sel``)
        are supported correctly.

        Args:
            log_id: Log service ID (e.g. "Sel", "Log1"). Optional.
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            Fully populated :class:`Log` resource.

        Raises:
            RedfishException: 404 when the system has no LogServices.
            RedfishValidationError: When ``log_id`` is None and multiple
                services exist.
            RedfishNotFoundError: When ``log_id`` is not in the collection.
        """
        from ._log_helpers import require_log_services_link, resolve_log_service

        system = self.get(system_id)
        odata_id = require_log_services_link(system, f"System {system.id!r}")
        return resolve_log_service(self._client, odata_id, log_id)

    def clear_system_log(
        self,
        log_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> None:
        """
        Invoke the ``#LogService.ClearLog`` action on a system log service.

        Args:
            log_id: Log service ID (e.g. "Sel", "Log1"). Optional
                — auto-selected when there is exactly one log
                service.
            system_id: System ID. Auto-selected if only one system exists.

        Raises:
            RedfishValidationError: If the log service does not expose ClearLog.
        """
        from ..models.common import RedfishResponse

        log = self.log_service(log_id, system_id)
        target = _extract_action_target(log.actions, "#LogService.ClearLog")
        if not target:
            raise RedfishValidationError(
                f"Log service {log.id!r} does not expose #LogService.ClearLog action"
            )
        logger.info("POST ClearLog -> %s", target)
        self._http.post(target, RedfishResponse, raw_body={})

    # ------------------------------------------------------------------
    # Drive helpers
    # ------------------------------------------------------------------

    def drive_by_odata_id(self, odata_id: str) -> Drive:
        """
        Fetch a single Drive resource directly by its ``@odata.id``.

        Useful when a Storage controller exposes only Link references and
        the caller needs the full Drive detail without enumerating chassis
        drives.

        Args:
            odata_id: Full ``@odata.id`` of the drive.

        Raises:
            RedfishNotFoundError: If the drive resource does not exist.
        """
        return self._http.get(odata_id, Drive)

    def drive_reset(self, drive_odata_id: str, reset_type: str) -> None:
        """
        Invoke the ``#Drive.Reset`` action on a drive (e.g. NVMe power cycle).

        Args:
            drive_odata_id: Full ``@odata.id`` of the drive.
            reset_type: Drive reset type, e.g. ``"GracefulShutdown"`` /
                ``"ForceOn"`` / ``"PowerCycle"``. Subject to the drive's
                ``ResetType@Redfish.AllowableValues``.

        Raises:
            RedfishValidationError: If the drive does not expose #Drive.Reset
                or ``reset_type`` is not in the drive's allowable values.
        """
        from ..models.common import RedfishResponse

        drive = self.drive_by_odata_id(drive_odata_id)
        action = _extract_action(drive.actions, "#Drive.Reset")
        if not action or not action.get("target"):
            raise RedfishValidationError(
                f"Drive {drive_odata_id} does not expose #Drive.Reset action"
            )
        target = action["target"]
        allowable = action.get("ResetType@Redfish.AllowableValues")
        if allowable and reset_type not in allowable:
            raise RedfishValidationError(
                f"Drive reset type '{reset_type}' not in allowable values {allowable}"
            )
        logger.info("POST Drive.Reset (%s) -> %s", reset_type, target)
        self._http.post(target, RedfishResponse, raw_body={"ResetType": reset_type})

    # ------------------------------------------------------------------
    # BootOptions collection
    # ------------------------------------------------------------------

    def boot_options(self, system_id: Optional[str] = None) -> List[BootOption]:
        """
        Get the BootOptions collection (modern boot model).

        Returns an empty list when the System does not expose a BootOptions
        link (vendor still uses the legacy ``BootSourceOverrideTarget`` model).

        Args:
            system_id: System ID. Auto-selected if only one system exists.
        """
        system = self.get(system_id)
        if not system.boot or not system.boot.boot_options:
            return []
        return self._client._get_collection(
            system.boot.boot_options.odata_id, BootOption
        )

    def boot_option(self, option_id: str, system_id: Optional[str] = None) -> BootOption:
        """
        Get a single BootOption resource.

        Args:
            option_id: BootOption ID (the trailing segment of its odata_id).
            system_id: System ID. Auto-selected if only one system exists.

        Raises:
            RedfishValidationError: If the System has no BootOptions collection.
            RedfishNotFoundError: If the option does not exist.
        """
        system = self.get(system_id)
        if not system.boot or not system.boot.boot_options:
            raise RedfishValidationError(
                "System does not expose a BootOptions collection"
            )
        path = f"{system.boot.boot_options.odata_id}/{option_id}"
        return self._http.get(path, BootOption)

    def set_boot_option_enabled(
        self,
        option_id: str,
        enabled: bool,
        system_id: Optional[str] = None,
    ) -> BootOption:
        """
        Toggle a single BootOption's ``BootOptionEnabled`` flag via PATCH.

        Args:
            option_id: BootOption ID.
            enabled: New value for BootOptionEnabled.
            system_id: System ID. Auto-selected if only one system exists.

        Returns:
            The BootOption re-read after the patch.
        """
        # Refresh ETag via GET before PATCH.
        option = self.boot_option(option_id, system_id)
        logger.info(
            "PATCH BootOptionEnabled=%s on %s", enabled, option.odata_id
        )
        self._http.patch_raw(
            option.odata_id, {"BootOptionEnabled": enabled}
        )
        return self._http.get(option.odata_id, BootOption)

    def fru_info(self, system_id: Optional[str] = None) -> Optional[Fru]:
        """
        Get FRU (Field Replaceable Unit) information for a system.
        Returns None if not available.


        """
        system = self.get(system_id)
        if system.oem is None or system.oem.bmc is None or system.oem.bmc.fru is None:
            return None
        fru_link = system.oem.bmc.fru
        return self._http.get(fru_link.odata_id, Fru)

    def gpus(self, system_id: Optional[str] = None) -> List[Gpu]:
        """
        Get GPU information for a system.

        This method uses a multi-step fallback strategy to handle different vendor
        implementations:

        1. Try /redfish/v1/Systems/{id}/GraphicsControllers (standard path)
        2. If empty, try /redfish/v1/Chassis/1/PCIeDevices and filter by name containing "GPU"
        3. If Chassis PCIeDevices is empty, try System.Links.PCIeDevices


        """
        system = self.get(system_id or "1")
        gpu_members: List[Gpu] = []

        # Step 1: Try GraphicsControllers (standard Redfish path)
        if system.graphics_controllers is not None:
            try:
                gpu_members = self._client._get_collection(
                    f"{system.odata_id}/GraphicsControllers", Gpu
                )
            except RedfishException as exc:
                logger.warning("GraphicsControllers fetch failed: %s", exc)

        if gpu_members:
            return gpu_members

        # Step 2: Try Chassis PCIeDevices (华为 xFusion, H3C etc.)
        from .chassis import ChassisManager
        chassis_mgr = ChassisManager(self._client)

        pcie_devices: List[PCIeDevice] = []
        try:
            chassis = chassis_mgr.get("1")
            if chassis.pcie_devices is not None:
                pcie_devices = self._client._get_collection(
                    chassis.pcie_devices.odata_id, PCIeDevice
                )
        except RedfishException as exc:
            logger.warning("Chassis PCIeDevices fetch failed: %s", exc)

        # Step 3: Fall back to System.Links.PCIeDevices
        if not pcie_devices and system.links and system.links.pcie_devices:
            for link in system.links.pcie_devices:
                try:
                    device = self._http.get(link.odata_id, PCIeDevice)
                    if device:
                        pcie_devices.append(device)
                except RedfishException as exc:
                    logger.warning("PCIeDevice fetch failed for %s: %s", link.odata_id, exc)

        # Filter GPU devices by name and convert to Gpu model
        for device in pcie_devices:
            if device.name and "GPU" in device.name:
                gpu = Gpu.model_construct(
                    odata_id=device.odata_id,
                    name=device.name,
                    manufacturer=device.manufacturer,
                    model=device.model,
                    power_watts="0",
                    version=device.part_number,
                )

                # Extract power watts from OEM if available
                if (device.oem and device.oem.gpu_oem_public and
                        device.oem.gpu_oem_public.power_watts > 0):
                    gpu.power_watts = str(device.oem.gpu_oem_public.power_watts)

                # Prefer card_model over part_number for version
                if device.card_model:
                    gpu.version = device.card_model

                # Set serial number from device
                if device.serial_number:
                    gpu.oem = GpuOEM.model_construct(serial_number=device.serial_number)

                gpu_members.append(gpu)

        return gpu_members

    def pcie_device(self, odata_id: str) -> PCIeDevice:
        """
        Get a specific PCIe device by its @odata.id.

        """
        return self._http.get(odata_id, PCIeDevice)

    def change_boot_source(
        self,
        target: str,
        system_id: Optional[str] = None,
        mode: str = BOOT_OVERRIDE_MODE_UEFI,
        enabled: str = BOOT_OVERRIDE_ENABLED_ONCE,
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
        system = self.get(system_id)
        boot = system.boot

        # Validate target against allowable values if provided by server
        if boot and boot.allowable_values and target not in boot.allowable_values:
            raise RedfishValidationError(
                f"Boot target '{target}' is not supported. "
                f"Allowable values: {boot.allowable_values}"
            )

        # If already set to the desired target, return current settings (no-op)
        if boot and boot.boot_source_override_target == target:
            logger.info("Boot source override target is already '%s', no change needed", target)
            req = SystemPatchSetting.model_construct(
                boot=BootSetting.model_construct(
                    boot_source_override_enabled=boot.boot_source_override_enabled,
                    boot_source_override_mode=boot.boot_source_override_mode,
                    boot_source_override_target=boot.boot_source_override_target,
                )
            )
            return req

        # Build PATCH request
        req = SystemPatchSetting.model_construct(
            boot=BootSetting.model_construct(
                boot_source_override_enabled=enabled,
                boot_source_override_mode=mode,
                boot_source_override_target=target,
            )
        )

        extra_headers = {}
        if system.odata_etag:
            extra_headers["If-Match"] = system.odata_etag

        return self._http.patch(
            system.odata_id, SystemPatchSetting, req, extra_headers
        )

    def reset(
        self,
        reset_type: str,
        system_id: Optional[str] = None,
        skip_power_state_check: bool = False,
    ):
        """
        Perform a system reset (power on/off/restart etc.).

        Validates that the requested reset type is compatible with the current
        power state before sending the request.



        Args:
            reset_type: Reset type string (e.g., "GracefulRestart", "ForceOff", "On")
            system_id: System ID. Auto-selected if only one system exists.
            skip_power_state_check: Skip power state compatibility check (some vendors
                don't properly report power state)

        Returns:
            RedfishResponse

        Raises:
            RedfishValidationError: If reset_type is incompatible with current power state
        """
        from ..models.common import RedfishResponse

        system = self.get(system_id)

        # Validate reset type against current power state
        if not skip_power_state_check and system.power_state:
            allowed_states = _RESET_ALLOWED.get(reset_type)
            if allowed_states and system.power_state not in allowed_states:
                raise RedfishValidationError(
                    f"Reset type '{reset_type}' is not compatible with current "
                    f"power state '{system.power_state}'. "
                    f"Allowed power states: {allowed_states}"
                )

        # Get the reset target URL from actions
        if not system.actions or not system.actions.computer_system_reset:
            raise RedfishException(400, "System reset action not found in system resource")

        reset_target = system.actions.computer_system_reset.target
        if not reset_target:
            raise RedfishException(400, "Reset action target URL is empty")

        logger.info("Resetting system %s with type=%s via %s",
                    system.id, reset_type, reset_target)

        return self._http.post(
            reset_target,
            RedfishResponse,
            raw_body={"ResetType": reset_type},
        )


# ---------------------------------------------------------------------------
# Internal helpers — Actions block parsing
# ---------------------------------------------------------------------------

def _extract_action(actions: Optional[dict], action_name: str) -> Optional[dict]:
    """Return the Action sub-dict for ``action_name`` or None."""
    if not actions or not isinstance(actions, dict):
        return None
    action = actions.get(action_name)
    if not isinstance(action, dict):
        return None
    return action


def _extract_action_target(actions: Optional[dict], action_name: str) -> Optional[str]:
    """Return the Action target URL for ``action_name`` or None."""
    action = _extract_action(actions, action_name)
    if not action:
        return None
    target = action.get("target")
    return target if isinstance(target, str) and target else None
