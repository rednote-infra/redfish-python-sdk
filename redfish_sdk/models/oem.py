"""
OEM (vendor-specific) data models.

Redfish allows vendors to extend standard resources with OEM fields.
This module models the common OEM fields used across Dell, HPE, xFusion,
Lenovo, Inspur (浪潮), Ningchang (宁畅), etc.

"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link


class MainBoard(Entity):
    """
    Mainboard (motherboard) FRU information.
    Field aliases support multiple vendor naming conventions.

    Inherits from Entity so that when parsed from a standalone FRU
    resource endpoint (e.g. ``/redfish/v1/Chassis/1/FruService/0``),
    standard fields like ``@odata.id``, ``Id``, ``Name`` are preserved.
    """

    chassis_part_number: Optional[str] = Field(None, alias="ChassisPartNumber")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    product_name: Optional[str] = Field(None, alias="ProductName")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    build_date: Optional[str] = Field(None, alias="BuildDate,ManufactureDate")
    pretty_name: Optional[str] = Field(None, alias="PrettyName")


class DeviceMaxNum(BaseModel):
    """Maximum number of each hardware component type."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    memory_num: Optional[int] = Field(None, alias="MemoryNum")
    pcie_num: Optional[int] = Field(None, alias="PCIeNum")
    cpu_num: Optional[int] = Field(None, alias="CPUNum")
    disk_num: Optional[int] = Field(None, alias="DiskNum")
    power_supply_num: Optional[int] = Field(None, alias="PowerSupplyNum")
    fan_num: Optional[int] = Field(None, alias="FanNum")


class Bmc(BaseModel):
    """
    BMC (Baseboard Management Controller) OEM extension fields.

    This is a catch-all model for OEM-specific fields from various vendors.
    Due to the wide variety of vendor implementations, most fields are optional.

    Key fields:
    - fru: Link to FRU data (华为 xFusion, 联想 etc.)
    - mainboard: Mainboard info (华为 iBMC)
    - bmc_version, cpld_version: Firmware version info
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # Product info
    product_name: Optional[str] = Field(None, alias="ProductName")
    bios_vendor: Optional[str] = Field(None, alias="BiosVendor")

    # Memory OEM (H3C)
    technology: Optional[str] = Field(None, alias="Technology")

    # Memory OEM (Ningchang 宁畅)
    mem_type: Optional[str] = Field(None, alias="Type")
    rank: Optional[str] = Field(None, alias="Rank")

    # NetworkAdapter OEM (Ningchang)
    name: Optional[str] = Field(None, alias="Name")
    driver_name: Optional[str] = Field(None, alias="DriverName")
    driver_version: Optional[str] = Field(None, alias="DriverVersion")
    card_manufacturer: Optional[str] = Field(None, alias="CardManufacturer")
    board_manufacturer: Optional[str] = Field(None, alias="BoardManufacturer")
    card_model: Optional[str] = Field(None, alias="CardModel")
    device_locator: Optional[str] = Field(None, alias="DeviceLocator")
    position: Optional[str] = Field(None, alias="Position")
    root_bdf: Optional[str] = Field(None, alias="RootBDF")

    # Chassis OEM
    mainboard: Optional[MainBoard] = Field(None, alias="Mainboard")
    device_max_num: Optional[DeviceMaxNum] = Field(None, alias="DeviceMaxNum")
    power_button_enabled: Optional[bool] = Field(None, alias="PowerButtonEnabled")

    # 浪潮 (Inspur) specific
    threshold_sensors: Optional[Link] = Field(None, alias="ThresholdSensors")
    discrete_sensors: Optional[Link] = Field(None, alias="DiscreteSensors")
    boards: Optional[Link] = Field(None, alias="Boards")
    backplanes: Optional[Link] = Field(None, alias="Backplanes")
    health_summary: Optional[Link] = Field(None, alias="HealthSummary")

    # Drive OEM (Inspur)
    rebuild_led: Optional[str] = Field(None, alias="RebuildLED")
    interface_type: Optional[str] = Field(None, alias="Interface")

    # Thermal OEM
    fan_speed_adjustment_mode: Optional[str] = Field(None, alias="FanSpeedAdjustmentMode")
    fan_speed_level_percents: Optional[int] = Field(None, alias="FanSpeedLevelPercents")

    # Power OEM
    line_output_voltage: Optional[float] = Field(None, alias="LineOutputVoltage")
    fan_speed: Optional[int] = Field(None, alias="FANSpeed")
    heatsink_temperature_celsius: Optional[float] = Field(None, alias="HeatsinkTemperatureCelsius")
    ambient_temperature_celsius: Optional[float] = Field(None, alias="AmbientTemperatureCelsius")
    total_power: Optional[int] = Field(None, alias="TotalPower")

    # System OEM
    configuration_model: Optional[str] = Field(None, alias="ConfigurationModel")
    bmc_version: Optional[str] = Field(None, alias="BMCVersion")
    cpld_version: Optional[str] = Field(None, alias="CPLDVersion")
    me_version: Optional[str] = Field(None, alias="MEVersion")
    psu_version: Optional[str] = Field(None, alias="PSUVersion")
    cpu_usage_percent: Optional[int] = Field(None, alias="CPUUsagePercent")
    memory_usage_percent: Optional[int] = Field(None, alias="MemoryUsagePercent")

    # FRU link (xFusion, Lenovo 等)
    fru: Optional[Link] = Field(None, alias="Fru")
    kvm: Optional[Link] = Field(None, alias="KVM")

    # Processor OEM
    current_speed_mhz: Optional[int] = Field(None, alias="CurrentSpeedMHz")
    l1_cache_kib: Optional[int] = Field(None, alias="L1CacheKiB")
    l2_cache_kib: Optional[int] = Field(None, alias="L2CacheKiB")
    l3_cache_kib: Optional[int] = Field(None, alias="L3CacheKiB")

    # Auth
    x_auth_token: Optional[str] = Field(None, alias="X-Auth-Token")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    part_number: Optional[str] = Field(None, alias="PartNumber")

    # Lenovo
    system_board_serial_number: Optional[str] = Field(None, alias="SystemBoardSerialNumber")
    fru_part_number: Optional[str] = Field(None, alias="FruPartNumber")


class Oem(BaseModel):
    """
    Top-level OEM wrapper used in most Redfish resources.

    The 'bmc' field accepts multiple vendor-specific keys:
    - Public (华为 iBMC / xFusion)
    - BMC
    - xFusion
    - Lenovo

    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # The SDK resolves vendor-specific OEM keys at parse time
    bmc: Optional[Bmc] = Field(None, alias="Public")
    host_post_code: Optional[List[Link]] = Field(None, alias="HostPostCode")
    fru_service: Optional[str] = Field(None, alias="FruService")

    def model_post_init(self, __context: Any) -> None:
        """
        After initialization, resolve vendor-specific OEM keys into the 'bmc' field.
        This replicates Java's @JsonAlias behavior for multi-vendor support.
        """
        if self.bmc is None:
            extra = self.model_extra or {}
            for key in ("BMC", "xFusion", "Lenovo", "Hpe", "Dell"):
                if key in extra and extra[key] is not None:
                    val = extra[key]
                    if isinstance(val, dict):
                        self.bmc = Bmc.model_validate(val)
                    elif isinstance(val, Bmc):
                        self.bmc = val
                    break
