"""
Power component models (PSU, voltage, power control).

"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status
from .cooling import ControlExcerpt, SensorExcerpt
from .oem import Oem
from .thermal import Redundancy


class InputRange(BaseModel):
    """Input voltage range for a power supply."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    input_type: Optional[str] = Field(None, alias="InputType")
    maximum_voltage: Optional[int] = Field(None, alias="MaximumVoltage")
    minimum_voltage: Optional[int] = Field(None, alias="MinimumVoltage")
    output_wattage: Optional[int] = Field(None, alias="OutputWattage")
    capacity_watts: Optional[float] = Field(None, alias="CapacityWatts")
    nominal_voltage_type: Optional[str] = Field(None, alias="NominalVoltageType")


class OutputRail(BaseModel):
    """Nominal output rail information for a modern PowerSupply resource."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    nominal_voltage: Optional[float] = Field(None, alias="NominalVoltage")
    physical_context: Optional[str] = Field(None, alias="PhysicalContext")


class PowerSupply(Entity):
    """
    Represents a power supply unit (PSU).
    Embedded in Power resource.

    """
    firmware_version: Optional[str] = Field(None, alias="FirmwareVersion")
    input_ranges: Optional[List[InputRange]] = Field(None, alias="InputRanges")
    input_nominal_voltage_type: Optional[str] = Field(
        None, alias="InputNominalVoltageType"
    )
    output_nominal_voltage_type: Optional[str] = Field(
        None, alias="OutputNominalVoltageType"
    )
    output_rails: Optional[List[OutputRail]] = Field(None, alias="OutputRails")
    metrics: Optional[Link] = Field(None, alias="Metrics")
    power_output_watts: Optional[int] = Field(None, alias="PowerOutputWatts", validate="type=int")
    # LineInputVoltage is defined as Number in DMTF Redfish PowerSupply schema,
    # which allows fractional values (e.g. 220.5). Use float to match the spec.
    line_input_voltage: Optional[float] = Field(None, alias="LineInputVoltage")
    line_input_voltage_type: Optional[str] = Field(None, alias="LineInputVoltageType")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="type=str")
    member_id: Optional[str] = Field(None, alias="MemberId")
    model: Optional[str] = Field(None, alias="Model", validate="type=str")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    power_capacity_watts: Optional[int] = Field(None, alias="PowerCapacityWatts", validate="type=int,gt=0")
    last_power_output_watts: Optional[int] = Field(None, alias="LastPowerOutputWatts")
    power_supply_type: Optional[str] = Field(None, alias="PowerSupplyType")
    related_item: Optional[List[Link]] = Field(None, alias="RelatedItem")
    serial_number: Optional[str] = Field(None, alias="SerialNumber", validate="type=str")
    spare_part_number: Optional[str] = Field(None, alias="SparePartNumber")
    power_input_watts: Optional[int] = Field(None, alias="PowerInputWatts", validate="type=int")
    redundancy: Optional[List[Redundancy]] = Field(None, alias="Redundancy")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    oem: Optional[Oem] = Field(None, alias="Oem")


class PowerAllocation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    allocated_watts: Optional[float] = Field(None, alias="AllocatedWatts")
    requested_watts: Optional[float] = Field(None, alias="RequestedWatts")


class PowerBrake(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    applied: Optional[bool] = Field(None, alias="Applied")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    load_percent_threshold: Optional[str] = Field(
        None, alias="LoadPercentThreshold"
    )
    temperature_threshold: Optional[str] = Field(
        None, alias="TemperatureThreshold"
    )


class PowerSubsystemLinks(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    power_brake_load_percent_sensor: Optional[Link] = Field(
        None, alias="PowerBrakeLoadPercentSensor"
    )
    power_brake_temperature_sensor: Optional[Link] = Field(
        None, alias="PowerBrakeTemperatureSensor"
    )
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class PowerSubsystem(Entity):
    """Modern chassis power subsystem and its advertised resource links."""

    allocation: Optional[PowerAllocation] = Field(None, alias="Allocation")
    batteries: Optional[Link] = Field(None, alias="Batteries")
    capacity_watts: Optional[float] = Field(None, alias="CapacityWatts")
    max_ramp_rate_watts_per_second: Optional[ControlExcerpt] = Field(
        None, alias="MaxRampRateWattsPerSecond"
    )
    power_brake: Optional[PowerBrake] = Field(None, alias="PowerBrake")
    power_supplies: Optional[Link] = Field(None, alias="PowerSupplies")
    power_supply_redundancy: Optional[List[Dict[str, Any]]] = Field(
        None, alias="PowerSupplyRedundancy"
    )
    links: Optional[PowerSubsystemLinks] = Field(None, alias="Links")
    status: Optional[Status] = Field(None, alias="Status")
    oem: Optional[Oem] = Field(None, alias="Oem")


class PowerSupplyMetrics(Entity):
    """Read-only measurements advertised by a modern PowerSupply resource."""

    charge_percent: Optional[SensorExcerpt] = Field(None, alias="ChargePercent")
    energy_kwh: Optional[SensorExcerpt] = Field(None, alias="EnergykWh")
    fan_speed_percent: Optional[SensorExcerpt] = Field(
        None, alias="FanSpeedPercent"
    )
    fan_speeds_percent: Optional[List[SensorExcerpt]] = Field(
        None, alias="FanSpeedsPercent"
    )
    frequency_hz: Optional[SensorExcerpt] = Field(None, alias="FrequencyHz")
    input_current_amps: Optional[SensorExcerpt] = Field(
        None, alias="InputCurrentAmps"
    )
    input_power_watts: Optional[SensorExcerpt] = Field(
        None, alias="InputPowerWatts"
    )
    input_voltage: Optional[SensorExcerpt] = Field(None, alias="InputVoltage")
    output_power_watts: Optional[SensorExcerpt] = Field(
        None, alias="OutputPowerWatts"
    )
    power_load_percent: Optional[SensorExcerpt] = Field(
        None, alias="PowerLoadPercent"
    )
    rail_current_amps: Optional[List[SensorExcerpt]] = Field(
        None, alias="RailCurrentAmps"
    )
    rail_power_watts: Optional[List[SensorExcerpt]] = Field(
        None, alias="RailPowerWatts"
    )
    rail_voltage: Optional[List[SensorExcerpt]] = Field(
        None, alias="RailVoltage"
    )
    temperature_celsius: Optional[SensorExcerpt] = Field(
        None, alias="TemperatureCelsius"
    )
    status: Optional[Status] = Field(None, alias="Status")
    oem: Optional[Oem] = Field(None, alias="Oem")


class Voltage(BaseModel):
    """Voltage sensor reading."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    member_id: Optional[str] = Field(None, alias="MemberId")
    name: Optional[str] = Field(None, alias="Name")
    physical_context: Optional[str] = Field(None, alias="PhysicalContext")
    reading_volts: Optional[float] = Field(None, alias="ReadingVolts")
    status: Optional[Status] = Field(None, alias="Status")
    upper_threshold_critical: Optional[float] = Field(None, alias="UpperThresholdCritical")
    lower_threshold_critical: Optional[float] = Field(None, alias="LowerThresholdCritical")


class PowerControl(BaseModel):
    """Represents overall power consumption metrics."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    member_id: Optional[str] = Field(None, alias="MemberId")
    name: Optional[str] = Field(None, alias="Name")
    power_capacity_watts: Optional[int] = Field(None, alias="PowerCapacityWatts")
    power_consumed_watts: Optional[float] = Field(None, alias="PowerConsumedWatts")
    power_requested_watts: Optional[float] = Field(None, alias="PowerRequestedWatts")
    power_available_watts: Optional[float] = Field(None, alias="PowerAvailableWatts")
    power_allocated_watts: Optional[float] = Field(None, alias="PowerAllocatedWatts")


class Power(Entity):
    """
    Power data (PSUs, voltages, power controls) for a chassis.
    Endpoint: /redfish/v1/Chassis/{chassisId}/Power

    """
    power_control: Optional[List[PowerControl]] = Field(None, alias="PowerControl")
    power_supplies: Optional[List[PowerSupply]] = Field(None, alias="PowerSupplies")
    redundancy: Optional[List[Redundancy]] = Field(None, alias="Redundancy")
    voltages: Optional[List[Voltage]] = Field(None, alias="Voltages")
    oem: Optional[Oem] = Field(None, alias="Oem")
