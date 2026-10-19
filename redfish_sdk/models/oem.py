"""
OEM (vendor-specific) data models.

Redfish allows vendors to extend standard resources with OEM fields.
This module models the common OEM fields used across Dell, HPE, xFusion,
Lenovo, Inspur (浪潮), Ningchang (宁畅), etc.

"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from .common import Entity, Link


class OemLink(BaseModel):
    """Link to an OEM resource whose published shape is not guaranteed.

    Vendors are inconsistent here: the same OEM key may be published as a Redfish
    link object, as an inlined resource object, or (on some firmware revisions)
    as a scalar. Modelling that key as a strict :class:`Link` would make a single
    odd response fail validation for the *whole* enclosing resource, taking down
    unrelated endpoints. Instead any non-dict shape collapses to an empty link:
    callers simply observe ``odata_id is None`` and take their normal fallback.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    odata_id: Optional[str] = Field(None, alias="@odata.id")

    @model_validator(mode="before")
    @classmethod
    def _accept_any_shape(cls, data: Any) -> dict:
        return data if isinstance(data, dict) else {}


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
    # Enginetech mainboard FRUs report the build date as "MfgDate", which is
    # neither the Redfish-standard "BuildDate" nor the "ManufactureDate" used by
    # some other vendors. Alias choices are tried in priority order.
    build_date: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("BuildDate", "ManufactureDate", "MfgDate"),
    )
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

    # NOTE: Fan/Drive OEM readings (SpeedRatio, drive temperature, DriveID,
    # ...) are intentionally NOT modelled here. Their location and casing
    # vary per vendor and would otherwise turn `Bmc` into a multi-vendor
    # dumping ground. They are read on demand via the
    # ``redfish_sdk.managers.oem_extractors`` strategy package, which reads
    # the raw values from `Oem.model_extra` / `Bmc.model_extra`
    # (pydantic `extra="allow"`) — no vendor-specific typed fields needed.

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

    # FRU link (xFusion, Lenovo etc.)
    fru: Optional[Link] = Field(None, alias="Fru")
    kvm: Optional[Link] = Field(None, alias="KVM")
    kvm_service: Optional[Link] = Field(None, alias="KvmService")

    # OEM service links (batch SDK-GAP elimination)
    ntp_service: Optional[Link] = Field(None, alias="NtpService")
    syslog_service: Optional[Link] = Field(None, alias="SyslogService")
    snmp_service: Optional[Link] = Field(None, alias="SnmpService")
    lldp_service: Optional[Link] = Field(None, alias="LldpService")
    dns_service: Optional[Link] = Field(None, alias="DnsService")
    rfb_service: Optional[Link] = Field(None, alias="RfbService")
    security_service: Optional[Link] = Field(None, alias="SecurityService")
    firewall_rules: Optional[Link] = Field(None, alias="FirewallRules")
    virtual_media_oem: Optional[Link] = Field(None, alias="VirtualMedia")
    sol_source_control_info: Optional[Link] = Field(None, alias="SOLSourceControlInfo")
    smtp_service: Optional[Link] = Field(None, alias="SmtpService")

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
    Top-level OEM wrapper. Merges vendor-specific keys into a single 'bmc' view.

    Vendor keys (in priority order): Public > BMC > xFusion > Lenovo > Hpe > Dell
    > gOemCustomeString. Public wins on conflict; others only fill None fields.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    bmc: Optional[Bmc] = Field(None, alias="Public")
    host_post_code: Optional[List[Link]] = Field(None, alias="HostPostCode")
    fru_service: Optional[str] = Field(None, alias="FruService")
    # Enginetech: /redfish/v1/Systems/Self/Oem/FruInfo
    fru_info: Optional[OemLink] = Field(None, alias="FruInfo")

    # NOTE: "Ami" and "Enginetech" are literal OEM root keys that may appear in a
    # BMC response, not vendor labels, so neither may be renamed. Enginetech BMCs
    # are AMI MegaRAC based: some SKUs publish their root OEM block as "Ami",
    # others publish it directly as "Enginetech". Keep both entries so OEM
    # merging never silently stops working.
    _VENDOR_KEYS = ("BMC", "xFusion", "Lenovo", "Hpe", "Dell", "gOemCustomeString", "Ami", "Enginetech")

    def model_post_init(self, __context: Any) -> None:
        extra = self.model_extra or {}
        for key in self._VENDOR_KEYS:
            val = extra.get(key)
            if val is None:
                continue
            if isinstance(val, dict):
                vendor_bmc = Bmc.model_validate(val)
            elif isinstance(val, Bmc):
                vendor_bmc = val
            else:
                continue
            if self.bmc is None:
                self.bmc = vendor_bmc
                continue
            for field_name in Bmc.model_fields:
                if getattr(self.bmc, field_name) is None:
                    v = getattr(vendor_bmc, field_name)
                    if v is not None:
                        setattr(self.bmc, field_name, v)
