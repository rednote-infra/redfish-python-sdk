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
    Thermal,
)
from ..models.thermal import InletHistoryTemperature

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

    def get(self, chassis_id: str = "1") -> Chassis:
        """
        Get a chassis resource by ID.

        Special handling: if the chassis collection URL already ends with "/{id}",
        use it directly to avoid double-appending (some vendors return the direct path).



        Args:
            chassis_id: Chassis ID (default "1")

        Returns:
            Chassis resource
        """
        odata_id = self._client._get_chassis_collection_odata_id()

        # If the collection odata_id already points to a specific chassis (ends with /1)
        # use it directly; otherwise append the chassis_id
        if odata_id.endswith(f"/{chassis_id}"):
            return self._http.get(odata_id, Chassis)

        return self._http.get(f"{odata_id}/{chassis_id}", Chassis)

    def thermal(self, chassis_id: str = "1") -> Thermal:
        """
        Get thermal information (fans and temperatures) for a chassis.


        """
        chassis = self.get(chassis_id)
        return self._http.get(chassis.thermal.odata_id, Thermal)

    def inlet_history_temperature(self, chassis_id: str = "1") -> Optional[InletHistoryTemperature]:
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
            chassis_id: Chassis ID (default "1")

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

    def power(self, chassis_id: str = "1") -> Power:
        """
        Get power information (PSUs and power controls) for a chassis.


        """
        chassis = self.get(chassis_id)
        return self._http.get(chassis.power.odata_id, Power)

    def drives(self, chassis_id: str = "1") -> List[Drive]:
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

        # Strategy 1: Use Chassis.Links.Drives
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

        # Strategy 2: Use Chassis.Drives collection endpoint
        if chassis.drives:
            try:
                return self._client._get_collection(chassis.drives.odata_id, Drive)
            except RedfishException as exc:
                logger.warning("Chassis.Drives collection failed: %s", exc)

        return []

    def network_adapters(self, chassis_id: str = "1") -> List[NetworkAdapter]:
        """
        Get the list of network adapters (NICs) in a chassis.


        """
        chassis = self.get(chassis_id)
        return self._client._get_collection(chassis.network_adapters.odata_id, NetworkAdapter)

    def pcie_devices(self, chassis_id: str = "1") -> List[PCIeDevice]:
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

    def fru_service(self, chassis_id: str = "1") -> List[dict]:
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

    def fru_service_board(self, chassis_id: str = "1") -> Optional[dict]:
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

    def set_indicator_led(self, state: str, chassis_id: str = "1") -> str:
        """
        Set the chassis IndicatorLED state via PATCH.

        Reads the chassis first so the HTTP layer has a fresh ETag for If-Match.

        Args:
            state: One of "Lit", "Blinking", "Off".
            chassis_id: Chassis ID (default "1").

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
        Set a Drive IndicatorLED state via PATCH on the drive resource.

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
        logger.info("PATCH IndicatorLED=%s on %s", state, drive_before.odata_id)
        self._http.patch_raw(drive_odata_id, {"IndicatorLED": state})
        drive_after = self._http.get(drive_odata_id, Drive)
        return drive_after.indicator_led


def _validate_indicator_led_state(state: str) -> None:
    if state not in _INDICATOR_LED_STATES:
        raise RedfishValidationError(
            f"Invalid IndicatorLED state '{state}'. "
            f"Allowed values: {list(_INDICATOR_LED_STATES)}"
        )
