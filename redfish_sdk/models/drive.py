"""
Drive (HDD/SSD/NVMe) component models.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Status


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
