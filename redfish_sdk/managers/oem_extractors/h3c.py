"""
H3C (新华三) OEM extractor.

H3C BMCs publish both fan speed and drive temperature under ``Public``
with the standard PascalCase field names:

    Fan.Oem.Public.SpeedRatio             (percent)
    Drive.Oem.Public.TemperatureCelsius   (Celsius)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .base import BaseOemExtractor, read_public_field, to_float

if TYPE_CHECKING:
    from ...models.drive import Drive
    from ...models.thermal import Fan


class H3cOemExtractor(BaseOemExtractor):
    """OEM field extractor for H3C (新华三) servers."""

    def get_fan_speed_ratio(self, fan: "Fan") -> Optional[float]:
        return to_float(read_public_field(fan.oem, "SpeedRatio"))

    def get_drive_temperature_celsius(self, drive: "Drive") -> Optional[float]:
        return to_float(read_public_field(drive.oem, "TemperatureCelsius"))
