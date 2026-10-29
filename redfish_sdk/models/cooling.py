"""Optional Redfish liquid-cooling equipment and measurement models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link, Status


class SensorExcerpt(BaseModel):
    """A sensor reading copied into another Redfish resource."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    data_source_uri: Optional[str] = Field(None, alias="DataSourceUri")
    reading: Optional[float] = Field(None, alias="Reading")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class FanSpeedExcerpt(SensorExcerpt):
    """Speed reading embedded in a standalone Redfish Fan resource."""

    speed_rpm: Optional[float] = Field(None, alias="SpeedRPM")


class PartLocation(BaseModel):
    """Service-facing physical location of a replaceable fan."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    location_ordinal_value: Optional[int] = Field(
        None, alias="LocationOrdinalValue"
    )
    location_type: Optional[str] = Field(None, alias="LocationType")
    orientation: Optional[str] = Field(None, alias="Orientation")
    reference: Optional[str] = Field(None, alias="Reference")
    service_label: Optional[str] = Field(None, alias="ServiceLabel")


class FanLocation(BaseModel):
    """Physical location block on a standalone Redfish Fan resource."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    part_location: Optional[PartLocation] = Field(None, alias="PartLocation")
    part_location_context: Optional[str] = Field(
        None, alias="PartLocationContext"
    )
    placement: Optional[Dict[str, Any]] = Field(None, alias="Placement")
    postal_address: Optional[Dict[str, Any]] = Field(
        None, alias="PostalAddress"
    )


class FanLinks(BaseModel):
    """Resources related to a standalone Redfish Fan."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    cooling_chassis: Optional[List[Link]] = Field(
        None, alias="CoolingChassis"
    )
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class Fan(Entity):
    """Modern standalone Fan resource under ``ThermalSubsystem.Fans``."""

    assembly: Optional[Link] = Field(None, alias="Assembly")
    fan_diameter_mm: Optional[float] = Field(None, alias="FanDiameterMm")
    hot_pluggable: Optional[bool] = Field(None, alias="HotPluggable")
    links: Optional[FanLinks] = Field(None, alias="Links")
    location: Optional[FanLocation] = Field(None, alias="Location")
    location_indicator_active: Optional[bool] = Field(
        None, alias="LocationIndicatorActive"
    )
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    model: Optional[str] = Field(None, alias="Model")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    physical_context: Optional[str] = Field(None, alias="PhysicalContext")
    power_watts: Optional[float] = Field(None, alias="PowerWatts")
    rated_secondary_speed_rpm: Optional[float] = Field(
        None, alias="RatedSecondarySpeedRPM"
    )
    rated_speed_rpm: Optional[float] = Field(None, alias="RatedSpeedRPM")
    replaceable: Optional[bool] = Field(None, alias="Replaceable")
    secondary_speed_percent: Optional[FanSpeedExcerpt] = Field(
        None, alias="SecondarySpeedPercent"
    )
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    spare_part_number: Optional[str] = Field(None, alias="SparePartNumber")
    speed_percent: Optional[FanSpeedExcerpt] = Field(
        None, alias="SpeedPercent"
    )
    status: Optional[Status] = Field(None, alias="Status")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class ControlExcerpt(BaseModel):
    """A control reading copied into another Redfish resource."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    allowable_max: Optional[float] = Field(None, alias="AllowableMax")
    allowable_min: Optional[float] = Field(None, alias="AllowableMin")
    control_mode: Optional[str] = Field(None, alias="ControlMode")
    data_source_uri: Optional[str] = Field(None, alias="DataSourceUri")
    default_set_point: Optional[float] = Field(None, alias="DefaultSetPoint")
    reading: Optional[float] = Field(None, alias="Reading")
    set_point: Optional[float] = Field(None, alias="SetPoint")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class Sensor(Entity):
    """A generic Redfish Sensor resource."""

    reading: Optional[float] = Field(None, alias="Reading")
    average_reading: Optional[float] = Field(None, alias="AverageReading")
    electrical_context: Optional[str] = Field(None, alias="ElectricalContext")
    lifetime_reading: Optional[float] = Field(None, alias="LifetimeReading")
    load_percent: Optional[float] = Field(None, alias="LoadPercent")
    power_factor: Optional[float] = Field(None, alias="PowerFactor")
    precision: Optional[float] = Field(None, alias="Precision")
    reading_type: Optional[str] = Field(None, alias="ReadingType")
    reading_units: Optional[str] = Field(None, alias="ReadingUnits")
    reading_time: Optional[str] = Field(None, alias="ReadingTime")
    reading_range_max: Optional[float] = Field(None, alias="ReadingRangeMax")
    reading_range_min: Optional[float] = Field(None, alias="ReadingRangeMin")
    upper_threshold_critical: Optional[float] = Field(None, alias="UpperThresholdCritical")
    upper_threshold_warning: Optional[float] = Field(None, alias="UpperThresholdWarning")
    lower_threshold_critical: Optional[float] = Field(None, alias="LowerThresholdCritical")
    lower_threshold_warning: Optional[float] = Field(None, alias="LowerThresholdWarning")
    speed_rpm: Optional[float] = Field(None, alias="SpeedRPM")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    physical_context: Optional[str] = Field(None, alias="PhysicalContext")
    physical_subcontext: Optional[str] = Field(None, alias="PhysicalSubContext")
    sensor_group: Optional[str] = Field(None, alias="SensorGroup")
    thresholds: Optional[Dict[str, Any]] = Field(None, alias="Thresholds")
    related_item: Optional[List[Link]] = Field(None, alias="RelatedItem")
    spare_part_number: Optional[str] = Field(None, alias="SparePartNumber")
    status: Optional[Status] = Field(None, alias="Status")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class EnvironmentMetrics(Entity):
    """Environmental readings advertised by a chassis or cooling unit."""

    absolute_humidity: Optional[SensorExcerpt] = Field(None, alias="AbsoluteHumidity")
    ambient_temperature_celsius: Optional[SensorExcerpt] = Field(
        None, alias="AmbientTemperatureCelsius"
    )
    current_amps: Optional[SensorExcerpt] = Field(None, alias="CurrentAmps")
    dew_point_celsius: Optional[SensorExcerpt] = Field(None, alias="DewPointCelsius")
    dew_point_proximity_celsius: Optional[SensorExcerpt] = Field(
        None, alias="DewPointProximityCelsius"
    )
    humidity_percent: Optional[SensorExcerpt] = Field(None, alias="HumidityPercent")
    energy_joules: Optional[SensorExcerpt] = Field(None, alias="EnergyJoules")
    energy_kwh: Optional[SensorExcerpt] = Field(None, alias="EnergykWh")
    fan_speeds_percent: Optional[List[SensorExcerpt]] = Field(
        None, alias="FanSpeedsPercent"
    )
    power_limit_watts: Optional[ControlExcerpt] = Field(
        None, alias="PowerLimitWatts"
    )
    power_load_percent: Optional[SensorExcerpt] = Field(None, alias="PowerLoadPercent")
    power_watts: Optional[SensorExcerpt] = Field(None, alias="PowerWatts")
    temperature_celsius: Optional[SensorExcerpt] = Field(None, alias="TemperatureCelsius")
    voltage: Optional[SensorExcerpt] = Field(None, alias="Voltage")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class CoolingUnitLinks(BaseModel):
    """Related resources for a CoolingUnit."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    chassis: Optional[List[Link]] = Field(None, alias="Chassis")
    managed_by: Optional[List[Link]] = Field(None, alias="ManagedBy")
    facility: Optional[Link] = Field(None, alias="Facility")


class CoolingUnit(Entity):
    """A coolant distribution unit or other liquid-cooling equipment."""

    equipment_type: Optional[str] = Field(None, alias="EquipmentType")
    asset_tag: Optional[str] = Field(None, alias="AssetTag")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    model: Optional[str] = Field(None, alias="Model")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    spare_part_number: Optional[str] = Field(None, alias="SparePartNumber")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    firmware_version: Optional[str] = Field(None, alias="FirmwareVersion")
    cooling_capacity_watts: Optional[int] = Field(None, alias="CoolingCapacityWatts")
    environment_metrics: Optional[Link] = Field(None, alias="EnvironmentMetrics")
    primary_coolant_connectors: Optional[Link] = Field(
        None, alias="PrimaryCoolantConnectors"
    )
    secondary_coolant_connectors: Optional[Link] = Field(
        None, alias="SecondaryCoolantConnectors"
    )
    links: Optional[CoolingUnitLinks] = Field(None, alias="Links")
    status: Optional[Status] = Field(None, alias="Status")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class CoolantConnector(Entity):
    """A liquid-cooling connector and its read-only measurements."""

    coolant_connector_type: Optional[str] = Field(None, alias="CoolantConnectorType")
    conductivity_ms_per_cm: Optional[SensorExcerpt] = Field(
        None, alias="ConductivityMSPerCm"
    )
    ph: Optional[SensorExcerpt] = Field(None, alias="pH")
    turbidity_ntu: Optional[SensorExcerpt] = Field(None, alias="TurbidityNTU")
    flow_liters_per_minute: Optional[SensorExcerpt] = Field(
        None, alias="FlowLitersPerMinute"
    )
    heat_removed_kw: Optional[SensorExcerpt] = Field(None, alias="HeatRemovedkW")
    delta_pressure_kpa: Optional[SensorExcerpt] = Field(None, alias="DeltaPressurekPa")
    supply_pressure_kpa: Optional[SensorExcerpt] = Field(None, alias="SupplyPressurekPa")
    return_pressure_kpa: Optional[SensorExcerpt] = Field(None, alias="ReturnPressurekPa")
    delta_temperature_celsius: Optional[SensorExcerpt] = Field(
        None, alias="DeltaTemperatureCelsius"
    )
    supply_temperature_celsius: Optional[SensorExcerpt] = Field(
        None, alias="SupplyTemperatureCelsius"
    )
    return_temperature_celsius: Optional[SensorExcerpt] = Field(
        None, alias="ReturnTemperatureCelsius"
    )
    dew_point_proximity_celsius: Optional[SensorExcerpt] = Field(
        None, alias="DewPointProximityCelsius"
    )
    valve_position_percent: Optional[SensorExcerpt] = Field(
        None, alias="ValvePositionPercent"
    )
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    model: Optional[str] = Field(None, alias="Model")
    part_number: Optional[str] = Field(None, alias="PartNumber")
    spare_part_number: Optional[str] = Field(None, alias="SparePartNumber")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    status: Optional[Status] = Field(None, alias="Status")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class ThermalSubsystem(Entity):
    """Modern chassis thermal subsystem links needed for cooling discovery."""

    coolant_connectors: Optional[Link] = Field(None, alias="CoolantConnectors")
    environment_metrics: Optional[Link] = Field(None, alias="EnvironmentMetrics")
    fans: Optional[Link] = Field(None, alias="Fans")
    sensors: Optional[Link] = Field(None, alias="Sensors")
    status: Optional[Status] = Field(None, alias="Status")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")
