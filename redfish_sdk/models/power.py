"""
Power component models (PSU, voltage, power control).

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status
from .oem import Oem
from .thermal import Redundancy


class InputRange(BaseModel):
    """Input voltage range for a power supply."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    input_type: Optional[str] = Field(None, alias="InputType")
    maximum_voltage: Optional[int] = Field(None, alias="MaximumVoltage")
    minimum_voltage: Optional[int] = Field(None, alias="MinimumVoltage")
    output_wattage: Optional[int] = Field(None, alias="OutputWattage")


class PowerSupply(Entity):
    """
    Represents a power supply unit (PSU).
    Embedded in Power resource.

    """
    firmware_version: Optional[str] = Field(None, alias="FirmwareVersion")
    input_ranges: Optional[List[InputRange]] = Field(None, alias="InputRanges")
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
