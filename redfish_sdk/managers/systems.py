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
from typing import TYPE_CHECKING, List, Optional, Union

from pydantic import ValidationError

from ..exceptions import RedfishException, RedfishValidationError
from ..models.actions import ActionInfo, ActionMap
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
    GraphicalConsoleAction,
    GraphicalConsoleGetOneTimeURLRequest,
    GraphicalConsoleGetOneTimeURLResponse,
    GraphicalConsoleSetOneTimePasswordRequest,
    GraphicalConsoleSetOneTimePasswordResponse,
    GraphicalConsoleSetPasswordRequest,
    Memory,
    Processor,
    Storage,
    System,
    SystemPatchSetting,
    Volume,
)
from .system_resources import select_member

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
            system_id: Advertised System Id or ``@odata.id``. If None,
                auto-selects the sole system.

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

        return select_member(self._client._get_systems_collection(), system_id)

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
        path = system.memory and system.memory.odata_id
        return self._client._get_collection(path or f"{system.odata_id}/Memory", Memory)

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
        storage = select_member(self.storages(system_id), storage_id)
        path = (
            storage.volumes.odata_id
            if storage.volumes and storage.volumes.odata_id
            else f"{storage.odata_id}/Volumes"
        )
        return self._client._get_collection(path, Volume)

    def bios(self, system_id: Optional[str] = None) -> Bios:
        """
        Get BIOS information for a system.


        """
        system = self.get(system_id)
        path = system.bios and system.bios.odata_id
        return self._http.get(path or f"{system.odata_id}/Bios", Bios)

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
            option_id: Advertised BootOption Id or ``@odata.id``.
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
        return select_member(self.boot_options(system_id), option_id)

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

        Supported layouts:
        1. Enginetech — ``System.Oem.FruInfo`` →
           ``{"FruInfo": {"MB_FRU": {"Board": ..., "Chassis": ..., "Product": ...}, ...}}``
        2. xFusion, Lenovo, etc. — ``System.Oem.Bmc.Fru`` link pointing at a
           standard ``Fru`` resource
        """
        system = self.get(system_id)

        # 1) Enginetech: Oem.FruInfo (a dict of FRU devices keyed by name; the
        #    mainboard usually sits under "MB_FRU")
        if system.oem is not None and system.oem.fru_info is not None:
            fru_url = system.oem.fru_info.odata_id
            if fru_url:
                try:
                    fru = _fru_from_enginetech(self._http.get_raw(fru_url))
                except RedfishException as exc:
                    logger.debug("Enginetech FruInfo fetch failed: %s", exc)
                    fru = None
                except ValidationError as exc:
                    # The BMC published a FruInfo payload our models reject (e.g. a
                    # non-string value in a string field). Degrade to the standard
                    # Oem.Bmc.Fru path below instead of surfacing it to the caller.
                    logger.debug("Enginetech FruInfo payload rejected by model: %s", exc)
                    fru = None
                if fru is not None:
                    return fru

        # 2) Standard OEM Fru link
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
        2. If empty, use the PCIeDevices link of the default advertised Chassis
           and filter by name containing "GPU"
        3. If Chassis PCIeDevices is empty, try System.Links.PCIeDevices


        """
        system = self.get(system_id or "1")
        gpu_members: List[Gpu] = []

        # Step 1: Try GraphicsControllers (standard Redfish path)
        if system.graphics_controllers is not None:
            try:
                gpu_members = self._client._get_collection(
                    system.graphics_controllers.odata_id, Gpu
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
            chassis = chassis_mgr.get()
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

    def graphical_console_get_one_time_url(
        self,
        console_type: Optional[str] = None,
        access_mode: Optional[str] = None,
        validity_period_seconds: Optional[int] = None,
        system_id: Optional[str] = None,
    ) -> GraphicalConsoleGetOneTimeURLResponse:
        """Request a temporary URL for an advertised system console."""
        system, action = self._graphical_console_action(
            system_id, "graphical_console_get_one_time_url",
            "#ComputerSystem.GraphicalConsoleGetOneTimeURL",
        )
        self._validate_graphical_console_parameters(
            system, action, console_type, access_mode,
            validity_period_seconds, "one-time URL",
        )
        request = GraphicalConsoleGetOneTimeURLRequest(
            console_type=console_type,
            access_mode=access_mode,
            validity_period_seconds=validity_period_seconds,
        )
        return self._http.post(
            action.target, GraphicalConsoleGetOneTimeURLResponse, body=request
        )

    def graphical_console_set_one_time_password(
        self,
        console_type: Optional[str] = None,
        access_mode: Optional[str] = None,
        password: Optional[str] = None,
        validity_period_seconds: Optional[int] = None,
        system_id: Optional[str] = None,
    ) -> GraphicalConsoleSetOneTimePasswordResponse:
        """Set or generate a temporary password for an advertised console."""
        system, action = self._graphical_console_action(
            system_id, "graphical_console_set_one_time_password",
            "#ComputerSystem.GraphicalConsoleSetOneTimePassword",
        )
        self._validate_graphical_console_parameters(
            system, action, console_type, access_mode,
            validity_period_seconds, "one-time password",
        )
        request = GraphicalConsoleSetOneTimePasswordRequest(
            console_type=console_type,
            access_mode=access_mode,
            password=password,
            validity_period_seconds=validity_period_seconds,
        )
        return self._http.post(
            action.target,
            GraphicalConsoleSetOneTimePasswordResponse,
            body=request,
        )

    def graphical_console_set_password(
        self,
        console_type: str,
        password: str,
        system_id: Optional[str] = None,
    ):
        """Set the persistent password for an advertised system console."""
        from ..models.common import RedfishResponse

        system, action = self._graphical_console_action(
            system_id, "graphical_console_set_password",
            "#ComputerSystem.GraphicalConsoleSetPassword",
        )
        self._validate_graphical_console_parameters(
            system, action, console_type, None, None, "persistent password"
        )
        request = GraphicalConsoleSetPasswordRequest(
            console_type=console_type, password=password
        )
        return self._http.post(action.target, RedfishResponse, body=request)

    def _graphical_console_action(
        self, system_id: Optional[str], attribute: str, action_name: str
    ) -> tuple[System, GraphicalConsoleAction]:
        system = self.get(system_id)
        if system.graphical_console is None:
            raise RedfishValidationError(
                "System does not advertise GraphicalConsole capabilities"
            )
        action = getattr(system.actions, attribute, None) if system.actions else None
        if action is None or not action.target:
            raise RedfishValidationError(
                f"System does not expose {action_name} action"
            )
        return system, action

    def _validate_graphical_console_parameters(
        self,
        system: System,
        action: GraphicalConsoleAction,
        console_type: Optional[str],
        access_mode: Optional[str],
        validity_period_seconds: Optional[int],
        operation: str,
    ) -> None:
        supplied = (console_type, access_mode, validity_period_seconds)
        info = (
            self._http.get(action.action_info, ActionInfo)
            if action.action_info and any(value is not None for value in supplied)
            else None
        )
        console_values = action.console_type_allowable_values
        if console_values is None and info:
            console_values = info.allowable_values("ConsoleType")
        access_values = action.access_mode_allowable_values
        if access_values is None and info:
            access_values = info.allowable_values("AccessMode")
        validity_values = action.validity_period_seconds_allowable_values
        if validity_values is None and info:
            validity_values = info.allowable_values("ValidityPeriodSeconds")
        _require_allowable("ConsoleType", console_type, console_values)
        _require_allowable("AccessMode", access_mode, access_values)
        _require_allowable(
            "ValidityPeriodSeconds", validity_period_seconds, validity_values
        )
        if validity_period_seconds is not None and validity_period_seconds < 1:
            raise RedfishValidationError(
                "ValidityPeriodSeconds must be greater than or equal to 1"
            )
        validity_parameter = (
            info.parameter("ValidityPeriodSeconds") if info else None
        )
        if validity_period_seconds is not None and validity_parameter:
            minimum = validity_parameter.minimum_value
            maximum = validity_parameter.maximum_value
            if minimum is not None and validity_period_seconds < minimum:
                raise RedfishValidationError(
                    f"ValidityPeriodSeconds must be at least {minimum:g}"
                )
            if maximum is not None and validity_period_seconds > maximum:
                raise RedfishValidationError(
                    f"ValidityPeriodSeconds must be at most {maximum:g}"
                )
        if console_type is None:
            return
        protocol = _console_protocol(system, console_type)
        if protocol is None:
            raise RedfishValidationError(
                f"ConsoleType '{console_type}' is not advertised by GraphicalConsole"
            )
        if protocol.service_enabled is False:
            raise RedfishValidationError(
                f"ConsoleType '{console_type}' is disabled"
            )
        modes = protocol.supported_access_modes or ["ReadWrite"]
        if access_mode is not None and access_mode not in modes:
            raise RedfishValidationError(
                f"AccessMode '{access_mode}' is not supported by {console_type}; "
                f"advertised values: {modes}"
            )
        capability = {
            "one-time URL": "supports_one_time_url",
            "one-time password": "supports_one_time_password",
            "persistent password": "supports_persistent_password",
        }[operation]
        if getattr(protocol, capability, None) is False:
            raise RedfishValidationError(
                f"ConsoleType '{console_type}' does not support {operation}"
            )


# ---------------------------------------------------------------------------
# Internal helpers — Actions block parsing
# ---------------------------------------------------------------------------


def _require_allowable(name, value, allowable) -> None:
    if value is not None and allowable is not None and value not in allowable:
        raise RedfishValidationError(
            f"{name} {value!r} is not in advertised allowable values {allowable}"
        )


def _console_protocol(system: System, console_type: str):
    console = system.graphical_console
    if console is None:
        return None
    attribute = {
        "VNC": "vnc",
        "RDP": "rdp",
        "HTML5": "html5",
        "KVMIP": "kvmip",
    }.get(console_type)
    return getattr(console, attribute, None) if attribute else None

# Enginetech — System.Oem.FruInfo parser
# ---------------------------------------------------------------------------

# Mainboard FRU key priority. Enginetech typically uses "MB_FRU"; some SKUs
# may use "MainBoard" or "MB".
_ENGINETECH_MAINBOARD_KEYS = ("MB_FRU", "MAINBOARD", "MB")


def _fru_from_enginetech(raw: Optional[dict]) -> Optional[Fru]:
    """Convert an Enginetech ``Oem/FruInfo`` raw response into a :class:`Fru`.

    Raw structure (key names and fields vary slightly across SKUs)::

        {"FruInfo": {"MB_FRU":   {"Board": {...}, "Chassis": {...}, "Product": {...}},
                     "PSU1_FRU": {"Product": {...}},
                     ...}}

    Args:
        raw: Raw JSON dict returned by ``get_raw()``.

    Returns:
        ``Fru`` object (with ``board`` taken from the mainboard FRU), or
        ``None`` if the layout cannot be recognised.
    """
    if not isinstance(raw, dict):
        return None

    devices = raw.get("FruInfo")
    if not isinstance(devices, dict):
        devices = raw

    # Locate the mainboard FRU entry
    entry: Optional[dict] = None
    for key in _ENGINETECH_MAINBOARD_KEYS:
        for name, val in devices.items():
            if key.lower() in str(name).lower() and isinstance(val, dict):
                entry = val
                break
        if entry is not None:
            break
    if entry is None:
        for val in devices.values():
            if isinstance(val, dict) and isinstance(val.get("Board"), dict):
                entry = val
                break
    if entry is None:
        logger.debug("Enginetech FruInfo: no mainboard entry found in %s", list(devices))
        return None

    board = dict(entry.get("Board") or {})
    chassis = entry.get("Chassis") if isinstance(entry.get("Chassis"), dict) else None
    product = entry.get("Product") if isinstance(entry.get("Product"), dict) else None

    if board:
        # Enginetech often leaves Board.ProductName blank (or as whitespace);
        # the real product name lives in the Product node, so back-fill it.
        if not str(board.get("ProductName") or "").strip() and product:
            fallback = str(product.get("ProductName") or "").strip()
            if fallback:
                board["ProductName"] = fallback
        # The chassis part number sits in the Chassis node; back-fill it into
        # MainBoard.ChassisPartNumber so the rest of the SDK sees it there.
        if not str(board.get("ChassisPartNumber") or "").strip() and chassis:
            chassis_pn = str(chassis.get("PartNumber") or "").strip()
            if chassis_pn:
                board["ChassisPartNumber"] = chassis_pn

    return Fru.model_validate(
        {
            "@odata.id": raw.get("@odata.id"),
            "MainBoard": board or None,
            "Chassis": chassis,
            "Product": product,
        }
    )


def _extract_action(actions: Optional[Union[dict, ActionMap]], action_name: str) -> Optional[dict]:
    """Return the Action sub-dict for ``action_name`` or None."""
    if not actions or not isinstance(actions, (dict, ActionMap)):
        return None
    action = actions.get(action_name)
    if not isinstance(action, dict):
        return None
    return action


def _extract_action_target(actions: Optional[Union[dict, ActionMap]], action_name: str) -> Optional[str]:
    """Return the Action target URL for ``action_name`` or None."""
    action = _extract_action(actions, action_name)
    if not action:
        return None
    target = action.get("target")
    return target if isinstance(target, str) and target else None
