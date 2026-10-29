"""
Drive (HDD/SSD/NVMe) component models.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .check import Field
from .common import Entity, Status
from .oem import Oem


class Location(BaseModel):
    """Physical location info."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    info: Optional[str] = Field(None, alias="Info")
    info_format: Optional[str] = Field(None, alias="InfoFormat")
    placement: Optional[Any] = Field(None, alias="Placement")
    postal_address: Optional[Any] = Field(None, alias="PostalAddress")


class Drive(Entity):
    """
    Represents a physical storage drive (HDD/SSD/NVMe).
    Endpoint: /redfish/v1/Chassis/{chassisId}/Drives/{driveId}

    """
    indicator_led: Optional[str] = Field(None, alias="IndicatorLED")
    location_indicator_active: Optional[bool] = Field(
        None, alias="LocationIndicatorActive"
    )
    model: Optional[str] = Field(None, alias="Model", validate="type=str")
    revision: Optional[str] = Field(None, alias="Revision")
    capacity_bytes: Optional[int] = Field(None, alias="CapacityBytes", validate="required,type=int,gt=0")
    protocol: Optional[str] = Field(None, alias="Protocol", validate="type=str")
    serial_number: Optional[str] = Field(None, alias="SerialNumber", validate="type=str")
    media_type: Optional[str] = Field(None, alias="MediaType", validate="type=str")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="type=str")
    capable_speed_gbs: Optional[Any] = Field(None, alias="CapableSpeedGbs")
    negotiated_speed_gbs: Optional[Any] = Field(None, alias="NegotiatedSpeedGbs")
    failure_predicted: Optional[bool] = Field(None, alias="FailurePredicted")
    predicted_media_life_left_percent: Optional[int] = Field(
        None, alias="PredictedMediaLifeLeftPercent"
    )
    hotspare_type: Optional[str] = Field(None, alias="HotspareType")
    status_indicator: Optional[str] = Field(None, alias="StatusIndicator")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    location: Optional[List[Location]] = Field(None, alias="Location")
    # Drive power state + Redfish Actions (e.g. #Drive.Reset).
    # `actions` is intentionally weakly typed (dict) because vendors vary widely
    # in how they expose action targets/AllowableValues. Helper methods on
    # SystemsManager parse the well-known sub-keys.
    power_state: Optional[str] = Field(None, alias="PowerState")
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")
    # Top-level drive temperature (宁畅 only, NOT under Oem)
    disk_temperature_celsius: Optional[float] = Field(None, alias="DiskTemperatureCelsius")
    oem: Optional[Oem] = Field(None, alias="Oem")

    @field_validator("location", mode="before")
    @classmethod
    def _normalize_location(cls, v):
        # Redfish allows Location to be either a single object or a list of
        # objects. Normalize a single dict into a one-element list so the
        # List[Location] typing stays consistent across vendors.
        if isinstance(v, dict):
            return [v]
        return v

    @model_validator(mode="after")
    def _provide_legacy_indicator_view(self):
        """Expose modern on/off state to callers of the deprecated field."""
        if (
            "location_indicator_active" in self.model_fields_set
            and "indicator_led" not in self.model_fields_set
            and self.location_indicator_active is not None
        ):
            object.__setattr__(
                self,
                "indicator_led",
                "Lit" if self.location_indicator_active else "Off",
            )
        return self
