"""
Thermal component models (Fan, Temperature, Redundancy).

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status
from .oem import Oem


class Fan(Entity):
    """
    Represents a cooling fan sensor reading.
    Embedded in Thermal resource.
    """
    lower_threshold_critical: Optional[int] = Field(None, alias="LowerThresholdCritical")
    lower_threshold_fatal: Optional[int] = Field(None, alias="LowerThresholdFatal")
    lower_threshold_non_critical: Optional[int] = Field(None, alias="LowerThresholdNonCritical")
    max_reading_range: Optional[int] = Field(None, alias="MaxReadingRange", validate="type=int,ge=0")
    member_id: Optional[str] = Field(None, alias="MemberId")
    min_reading_range: Optional[int] = Field(None, alias="MinReadingRange", validate="type=int,ge=0")
    physical_context: Optional[str] = Field(None, alias="PhysicalContext")
    reading: Optional[int] = Field(None, alias="Reading", validate="type=int,ge=0")
    reading_units: Optional[str] = Field(None, alias="ReadingUnits", validate="type=str")
    related_item: Optional[List[Link]] = Field(None, alias="RelatedItem")
    redundancy: Optional[List[Link]] = Field(None, alias="Redundancy")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    upper_threshold_critical: Optional[int] = Field(None, alias="UpperThresholdCritical")
    upper_threshold_fatal: Optional[int] = Field(None, alias="UpperThresholdFatal")
    upper_threshold_non_critical: Optional[int] = Field(None, alias="UpperThresholdNonCritical")


class Temperature(Entity):
    """
    Represents a temperature sensor reading.
    Embedded in Thermal resource.
    """
    max_reading_range_temp: Optional[int] = Field(None, alias="MaxReadingRangeTemp")
    member_id: Optional[str] = Field(None, alias="MemberId")
    min_reading_range_temp: Optional[int] = Field(None, alias="MinReadingRangeTemp")
    physical_context: Optional[str] = Field(None, alias="PhysicalContext", validate="type=str")
    reading_celsius: Optional[float] = Field(None, alias="ReadingCelsius", validate="type=float")
    sensor_number: Optional[int] = Field(None, alias="SensorNumber")
    related_item: Optional[List[Link]] = Field(None, alias="RelatedItem")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    upper_threshold_critical: Optional[int] = Field(None, alias="UpperThresholdCritical")
    upper_threshold_fatal: Optional[int] = Field(None, alias="UpperThresholdFatal")
    upper_threshold_non_critical: Optional[int] = Field(None, alias="UpperThresholdNonCritical")
    lower_threshold_critical: Optional[int] = Field(None, alias="LowerThresholdCritical")
    lower_threshold_fatal: Optional[int] = Field(None, alias="LowerThresholdFatal")
    lower_threshold_non_critical: Optional[int] = Field(None, alias="LowerThresholdNonCritical")


class Redundancy(BaseModel):
    """Redundancy configuration info."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    member_id: Optional[str] = Field(None, alias="MemberId")
    mode: Optional[str] = Field(None, alias="Mode")
    name: Optional[str] = Field(None, alias="Name")
    status: Optional[Status] = Field(None, alias="Status")
    redundancy_set: Optional[List[Link]] = Field(None, alias="RedundancySet")


class HistoricalInletTempEntry(BaseModel):
    """
    A single historical inlet temperature sample.
    Embedded in InletHistoryTemperature.HistoricalInletTemp.

    Note: BMC returns ``avg`` / ``max`` / ``min`` / ``time`` as lower-case keys,
    while ``Description`` follows PascalCase. Aliases preserve the original
    casing for round-trip fidelity.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    description: Optional[str] = Field(None, alias="Description")
    avg: Optional[float] = Field(None, alias="avg", validate="type=float")
    max: Optional[float] = Field(None, alias="max", validate="type=float")
    min: Optional[float] = Field(None, alias="min", validate="type=float")
    time: Optional[str] = Field(None, alias="time")


class InletHistoryTemperature(Entity):
    """
    Air inlet historical temperature samples for a chassis.
    Endpoint: /redfish/v1/Chassis/{chassisId}/Thermal/InletHistoryTemperature

    Vendor-specific sub-resource (e.g., 华为 / xFusion iBMC) referenced from
    the Thermal resource via the ``InletHistoryTemperature`` odata link.
    """
    description: Optional[str] = Field(None, alias="Description")
    historical_inlet_temp: Optional[List[HistoricalInletTempEntry]] = Field(
        None, alias="HistoricalInletTemp"
    )


class Thermal(Entity):
    """
    Thermal data (fans and temperatures) for a chassis.
    Endpoint: /redfish/v1/Chassis/{chassisId}/Thermal
    """
    fans: Optional[List[Fan]] = Field(None, alias="Fans")
    temperatures: Optional[List[Temperature]] = Field(None, alias="Temperatures")
    redundancy: Optional[List[Redundancy]] = Field(None, alias="Redundancy")
    inlet_history_temperature: Optional[Link] = Field(None, alias="InletHistoryTemperature")
    oem: Optional[Oem] = Field(None, alias="Oem")
