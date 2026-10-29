"""
Chassis manager — manages physical server enclosure resources.

Provides access to:
- Chassis info (manufacturer, model, serial number, power state)
- Thermal data (fan speeds, temperatures)
- Power data (PSUs, voltage, power control)
- Drives (HDDs/SSDs/NVMe with multi-vendor fallback)
- Network adapters (NICs)
- PCIe devices (GPU, HBA, etc.)
- FRU service data

"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from ..exceptions import (
    RedfishException,
    RedfishNotFoundError,
    RedfishValidationError,
)
from ..models.chassis import (
    Chassis,
    Drive,
    NetworkAdapter,
    PCIeDevice,
    Power,
    PowerSubsystem,
    PowerSupply,
    PowerSupplyMetrics,
    Thermal,
)
from ..models.thermal import InletHistoryTemperature
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)

# Allowed IndicatorLED states per Redfish spec.
_INDICATOR_LED_STATES = ("Lit", "Blinking", "Off")


class ChassisManager:
    """
    Manages Redfish Chassis resources.


    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def get(self, chassis_id: Optional[str] = "1") -> Chassis:
        """
        Get a chassis resource by ID.

        Args:
            chassis_id: Chassis ID. ``None`` uses the compatibility default
                ``"1"``. If that member is not found, the advertised
                Chassis collection is used as a fallback.

        Returns:
            Chassis resource
        """
        chassis_id = chassis_id or "1"

        if chassis_id != "1":
            return select_member(
                self._client._get_chassis_collection(), chassis_id
            )

        odata_id = self._client._get_chassis_collection_odata_id()

        # If the collection odata_id already points to a specific chassis (ends with /1)
        # use it directly; otherwise append the chassis_id
        resource_url = (
            odata_id if odata_id.endswith(f"/{chassis_id}")
            else f"{odata_id}/{chassis_id}"
        )
        try:
            return self._http.get(resource_url, Chassis)
        except RedfishNotFoundError:
            if chassis_id != "1":
                raise
            chassis_members = self._client._get_chassis_collection()
            if not chassis_members:
                raise
            return chassis_members[0]

    def thermal(self, chassis_id: Optional[str] = None) -> Thermal:
        """
        Get thermal information (fans and temperatures) for a chassis.


        """
        chassis = self.get(chassis_id)
        return self._http.get(chassis.thermal.odata_id, Thermal)

    def get_fan_speed_ratio(self, fan) -> Optional[float]:
        """
        Return the normalized fan speed as a percentage (0-100).

        Automatically detects the server vendor and dispatches to the
        matching :class:`~redfish_sdk.managers.oem_extractors.BaseOemExtractor`
        so callers do not need to know which OEM sub-key
        (``xFusion`` / ``Public`` / ``gOemCustomeString`` / ...) the BMC
        publishes ``SpeedRatio`` under. Vendors that do not publish an OEM
        ``SpeedRatio`` (Lenovo, Nettrix) fall back to a
        ``Reading / MaxReadingRange`` derivation inside the extractor.

        Args:
            fan: A :class:`~redfish_sdk.models.thermal.Fan` obtained from
                :meth:`thermal`.

        Returns:
            Fan speed percent, or ``None`` when the BMC provides neither an
            OEM ``SpeedRatio`` nor a usable ``Reading`` / ``MaxReadingRange``
            pair.
        """
        from .oem_extractors import OemExtractorRegistry, VendorDetector
        vendor = VendorDetector.detect(self._client)
        return OemExtractorRegistry.get(vendor).get_fan_speed_ratio(fan)

    def get_drive_temperature_celsius(self, drive) -> Optional[float]:
        """
        Return the drive temperature in Celsius, or ``None`` when unknown.

        Automatically detects the server vendor and dispatches to the
        matching extractor so callers do not need to handle vendor-specific
        readings such as ``Oem.xFusion.TemperatureCelsius``,
        ``Oem.Public.temperature`` (lowercase for Lenovo / Inspur),
        ``Oem.Public.TemperatureCelsius`` (H3C / ZTE), or Nettrix's
        top-level ``Drive.DiskTemperatureCelsius``.

        Args:
            drive: A :class:`~redfish_sdk.models.drive.Drive` obtained from
                :meth:`SystemsManager.drive_info` or a drives listing.

        Returns:
            Drive temperature in Celsius, or ``None`` when the BMC does not
            expose a drive temperature via any known OEM location.
        """
        from .oem_extractors import OemExtractorRegistry, VendorDetector
        vendor = VendorDetector.detect(self._client)
        return OemExtractorRegistry.get(vendor).get_drive_temperature_celsius(drive)

    def inlet_history_temperature(self, chassis_id: Optional[str] = None) -> Optional[InletHistoryTemperature]:
        """
        Get air inlet historical temperature samples for a chassis.

        Discovery flow:
          1. Fetch the Thermal resource via ``thermal(chassis_id)``.
          2. Read ``Thermal.inlet_history_temperature.odata_id``.
          3. GET that URL and parse as :class:`InletHistoryTemperature`.

        Returns ``None`` when the sub-resource is not advertised by the BMC
        or returns 404 (vendor does not implement it). Other transport errors
        (auth failure, network issues, etc.) propagate to the caller.

        Args:
            chassis_id: Chassis ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            InletHistoryTemperature model, or None when not supported.
        """
        thermal = self.thermal(chassis_id)
        if thermal.inlet_history_temperature is None:
            logger.debug("Thermal resource has no InletHistoryTemperature link")
            return None

        odata_id = thermal.inlet_history_temperature.odata_id
        try:
            return self._http.get(odata_id, InletHistoryTemperature)
        except RedfishNotFoundError as exc:
            logger.debug("InletHistoryTemperature not found at %s: %s", odata_id, exc)
            return None

    def power(self, chassis_id: Optional[str] = None) -> Power:
        """
        Get power information (PSUs and power controls) for a chassis.


        """
        chassis = self.get(chassis_id)
        if not chassis.power or not chassis.power.odata_id:
            raise RedfishNotFoundError("Chassis does not advertise legacy Power")
        return self._http.get(chassis.power.odata_id, Power)

    def power_subsystem(
        self, chassis_id: Optional[str] = None
    ) -> PowerSubsystem:
        """Get the modern PowerSubsystem through its advertised chassis link."""
        chassis = self.get(chassis_id)
        link = chassis.power_subsystem
        if not link or not link.odata_id:
            raise RedfishNotFoundError("Chassis does not advertise PowerSubsystem")
        return self._http.get(link.odata_id, PowerSubsystem)

    def power_supplies(
        self, chassis_id: Optional[str] = None
    ) -> List[PowerSupply]:
        """Prefer modern PowerSupply resources and fall back to legacy Power."""
        chassis = self.get(chassis_id)
        if chassis.power_subsystem and chassis.power_subsystem.odata_id:
            try:
                subsystem = self._http.get(
                    chassis.power_subsystem.odata_id, PowerSubsystem
                )
                if subsystem.power_supplies and subsystem.power_supplies.odata_id:
                    return self._client._get_collection(
                        subsystem.power_supplies.odata_id, PowerSupply
                    )
            except RedfishNotFoundError:
                logger.debug(
                    "Modern PowerSubsystem is unavailable; trying legacy Power"
                )

        if not chassis.power or not chassis.power.odata_id:
            return []
        legacy_power = self._http.get(chassis.power.odata_id, Power)
        return legacy_power.power_supplies or []

    def power_supply(
        self,
        identifier: Optional[str] = None,
        chassis_id: Optional[str] = None,
    ) -> PowerSupply:
        """Select an advertised modern or legacy power supply."""
        return select_member(
            self.power_supplies(chassis_id),
            identifier,
            aliases=("member_id",),
        )

    def power_supply_metrics(
        self,
        identifier: Optional[str] = None,
        chassis_id: Optional[str] = None,
    ) -> PowerSupplyMetrics:
        """Get read-only metrics through a selected PowerSupply Metrics link."""
        supplies = self.power_supplies(chassis_id)
        if not supplies:
            raise RedfishNotFoundError(
                "Chassis does not advertise PowerSupplyMetrics"
            )
        supply = select_member(supplies, identifier, aliases=("member_id",))
        if not supply.metrics or not supply.metrics.odata_id:
            raise RedfishNotFoundError(
                f"PowerSupply {supply.id or supply.member_id!r} does not "
                "advertise PowerSupplyMetrics"
            )
        return self._http.get(supply.metrics.odata_id, PowerSupplyMetrics)

    def drives(self, chassis_id: Optional[str] = None) -> List[Drive]:
        """
        Get the list of physical drives in a chassis.

        Multi-vendor fallback strategy:
        1. Try Chassis.Links.Drives[0] as a collection endpoint
        2. If that returns empty/no members, fetch each link individually
        3. Fall back to Chassis.Drives if Links.Drives is not set


        multi-vendor fallback logic.

        Returns:
            List of Drive objects
        """
        chassis = self.get(chassis_id)

        # Strategy 1: Chassis.Drives (canonical chassis-owned drive collection).
        # Preferred because some BMCs expose the authoritative Drive resources
        # (with fields such as IndicatorLED) only here, while Chassis.Links.Drives
        # may resolve to Storage-side Drive references that lack those fields.
        if chassis.drives:
            try:
                drives = self._client._get_collection(chassis.drives.odata_id, Drive)
                if drives:
                    return drives
            except RedfishException as exc:
                logger.warning("Chassis.Drives collection failed: %s", exc)

        # Strategy 2: Chassis.Links.Drives (links may resolve to Storage-side
        # Drive resources). Kept as fallback for BMCs that only populate links.
        if chassis.links and chassis.links.drives:
            drive_links = chassis.links.drives
            if drive_links:
                # Try first link as a collection endpoint
                first_link = drive_links[0]
                try:
                    drives = self._client._get_collection(first_link.odata_id, Drive)
                    if drives:
                        return drives
                except RedfishException:
                    pass

                # If collection is empty, fetch each link individually
                result = []
                for link in drive_links:
                    try:
                        drive = self._http.get(link.odata_id, Drive)
                        if drive:
                            result.append(drive)
                    except RedfishException as exc:
                        logger.warning("Failed to fetch drive %s: %s", link.odata_id, exc)

                if result:
                    return result

        return []

    def network_adapters(self, chassis_id: Optional[str] = None) -> List[NetworkAdapter]:
        """
        Get the list of network adapters (NICs) in a chassis.


        """
        chassis = self.get(chassis_id)
        return self._client._get_collection(chassis.network_adapters.odata_id, NetworkAdapter)

    def pcie_devices(self, chassis_id: Optional[str] = None) -> List[PCIeDevice]:
        """
        Get the list of PCIe devices in a chassis.

        Multi-vendor fallback strategy:
        1. Try Chassis.PCIeDevices collection endpoint
        2. Fall back to Chassis.Links.PCIeDevices (individual links)



        Returns:
            List of PCIeDevice objects
        """
        chassis = self.get(chassis_id)

        # Strategy 1: Use Chassis.PCIeDevices collection endpoint
        if chassis.pcie_devices:
            try:
                return self._client._get_collection(chassis.pcie_devices.odata_id, PCIeDevice)
            except RedfishException as exc:
                logger.warning("Chassis.PCIeDevices collection failed: %s", exc)

        # Strategy 2: Use Chassis.Links.PCIeDevices individual links
        if chassis.links and chassis.links.pcie_devices:
            return self._client._get_list(chassis.links.pcie_devices, PCIeDevice)

        return []

    def fru_service(self, chassis_id: Optional[str] = None) -> List[dict]:
        """
        Get FRU service data from the chassis OEM extension.

        This is a vendor-specific (华为 iBMC) feature that provides
        detailed FRU board info via /redfish/v1/Chassis/{id}/FruService.



        Returns:
            List of raw FRU service data dicts
        """
        chassis = self.get(chassis_id)
        if chassis.oem is None or chassis.oem.fru_service is None:
            return []

        fru_service_url = chassis.oem.fru_service
        try:
            collection_raw = self._http.get_raw(fru_service_url)
            members = collection_raw.get("Members", [])
            results = []
            for member in members:
                member_id = member.get("@odata.id")
                if member_id:
                    try:
                        fru_data = self._http.get_raw(member_id)
                        results.append(fru_data)
                    except RedfishException as exc:
                        logger.warning("Failed to fetch FRU service %s: %s", member_id, exc)
            return results
        except RedfishException as exc:
            logger.warning("FRU service collection failed: %s", exc)
            return []

    def fru_service_board(self, chassis_id: Optional[str] = None) -> Optional[dict]:
        """
        Get the primary FRU board info (the '/0' member of the FRU service collection).


        """
        chassis = self.get(chassis_id)
        if chassis.oem is None or chassis.oem.fru_service is None:
            return None

        fru_service_url = chassis.oem.fru_service
        try:
            collection_raw = self._http.get_raw(fru_service_url)
            members = collection_raw.get("Members", [])
            for member in members:
                member_id = member.get("@odata.id", "")
                if member_id.endswith("/0"):
                    return self._http.get_raw(member_id)
        except RedfishException as exc:
            logger.warning("FRU service board fetch failed: %s", exc)

        return None

    # ------------------------------------------------------------------
    # IndicatorLED write helpers
    # ------------------------------------------------------------------

    def set_indicator_led(self, state: str, chassis_id: Optional[str] = None) -> str:
        """
        Set the chassis IndicatorLED state via PATCH.

        Reads the chassis first so the HTTP layer has a fresh ETag for If-Match.

        Args:
            state: One of "Lit", "Blinking", "Off".
            chassis_id: Chassis ID. Uses default "1" when omitted; discovers a collection member only after a 404.

        Returns:
            The IndicatorLED value after the patch (re-read from BMC).

        Raises:
            RedfishValidationError: If ``state`` is not an allowed value.
        """
        _validate_indicator_led_state(state)
        chassis = self.get(chassis_id)
        logger.info("PATCH IndicatorLED=%s on %s", state, chassis.odata_id)
        self._http.patch_raw(chassis.odata_id, {"IndicatorLED": state})
        return self.get(chassis_id).indicator_led

    def set_drive_indicator_led(self, drive_odata_id: str, state: str) -> str:
        """
        Set a drive identification state using the deprecated string API.

        ``IndicatorLED`` is preserved when the drive advertises it. For a
        modern-only drive, ``Lit`` and ``Off`` are translated to
        ``LocationIndicatorActive``. ``Blinking`` cannot be represented by
        the modern boolean property.

        Args:
            drive_odata_id: Full ``@odata.id`` of the drive resource.
            state: One of "Lit", "Blinking", "Off".

        Returns:
            The IndicatorLED value after the patch (re-read from BMC).

        Raises:
            RedfishValidationError: If ``state`` is not an allowed value.
        """
        _validate_indicator_led_state(state)
        # Refresh ETag before PATCH.
        drive_before = self._http.get(drive_odata_id, Drive)
        advertised = drive_before.model_fields_set
        if "indicator_led" in advertised:
            property_name = "IndicatorLED"
            value = state
        elif "location_indicator_active" in advertised:
            if state == "Blinking":
                raise RedfishValidationError(
                    "Drive advertises LocationIndicatorActive only; "
                    "Blinking cannot be represented by this boolean property"
                )
            property_name = "LocationIndicatorActive"
            value = state == "Lit"
        else:
            _raise_drive_indicator_unsupported(drive_odata_id)

        logger.info("PATCH %s=%s on %s", property_name, value, drive_before.odata_id)
        self._http.patch_raw(drive_odata_id, {property_name: value})
        drive_after = self._http.get(drive_odata_id, Drive)
        if property_name == "IndicatorLED":
            return drive_after.indicator_led
        return "Lit" if drive_after.location_indicator_active else "Off"

    def set_drive_location_indicator(
        self, drive_odata_id: str, active: bool
    ) -> bool:
        """Set drive identification using the best advertised property.

        The standard ``LocationIndicatorActive`` property is preferred. The
        deprecated ``IndicatorLED`` property is used only as a fallback.
        Reading the drive before PATCH refreshes its cached ETag and prevents
        sending a property that the resource did not advertise.
        """
        if not isinstance(active, bool):
            raise RedfishValidationError(
                "Drive location indicator state must be a boolean"
            )

        drive_before = self._http.get(drive_odata_id, Drive)
        advertised = drive_before.model_fields_set
        if "location_indicator_active" in advertised:
            property_name = "LocationIndicatorActive"
            value = active
        elif "indicator_led" in advertised:
            property_name = "IndicatorLED"
            value = "Lit" if active else "Off"
        else:
            _raise_drive_indicator_unsupported(drive_odata_id)

        logger.info("PATCH %s=%s on %s", property_name, value, drive_before.odata_id)
        self._http.patch_raw(drive_odata_id, {property_name: value})
        drive_after = self._http.get(drive_odata_id, Drive)
        if property_name == "LocationIndicatorActive":
            return drive_after.location_indicator_active
        return drive_after.indicator_led != "Off"


def _validate_indicator_led_state(state: str) -> None:
    if state not in _INDICATOR_LED_STATES:
        raise RedfishValidationError(
            f"Invalid IndicatorLED state '{state}'. "
            f"Allowed values: {list(_INDICATOR_LED_STATES)}"
        )


def _raise_drive_indicator_unsupported(drive_odata_id: str) -> None:
    raise RedfishValidationError(
        f"Drive {drive_odata_id} does not advertise "
        "LocationIndicatorActive or IndicatorLED"
    )
