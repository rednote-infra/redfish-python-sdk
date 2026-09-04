"""
xFusion (超聚变) OEM extractor.

xFusion iBMC exposes fan speed and drive temperature under the
``xFusion`` OEM sub-key:

    Fan.Oem.xFusion.SpeedRatio             (percent, integer)
    Drive.Oem.xFusion.TemperatureCelsius   (Celsius, numeric string)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .base import BaseOemExtractor, read_vendor_field, to_float

if TYPE_CHECKING:
    from ...models.drive import Drive
    from ...models.thermal import Fan


class XFusionOemExtractor(BaseOemExtractor):
    """OEM field extractor for xFusion (超聚变) servers."""

    def get_fan_speed_ratio(self, fan: "Fan") -> Optional[float]:
        return to_float(read_vendor_field(fan.oem, "xFusion", "SpeedRatio"))

    def get_drive_temperature_celsius(self, drive: "Drive") -> Optional[float]:
        return to_float(
            read_vendor_field(drive.oem, "xFusion", "TemperatureCelsius")
        )
