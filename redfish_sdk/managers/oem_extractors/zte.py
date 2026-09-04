"""
ZTE (中兴) OEM extractor.

ZTE BMCs publish both fan speed and drive temperature under ``Public``
with the standard PascalCase field names (identical shape to H3C in the
observed dumps):

    Fan.Oem.Public.SpeedRatio             (percent)
    Drive.Oem.Public.TemperatureCelsius   (Celsius)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .base import BaseOemExtractor, read_public_field, to_float

if TYPE_CHECKING:
    from ...models.drive import Drive
    from ...models.thermal import Fan


class ZteOemExtractor(BaseOemExtractor):
    """OEM field extractor for ZTE (中兴) servers."""

    def get_fan_speed_ratio(self, fan: "Fan") -> Optional[float]:
        return to_float(read_public_field(fan.oem, "SpeedRatio"))

    def get_drive_temperature_celsius(self, drive: "Drive") -> Optional[float]:
        return to_float(read_public_field(drive.oem, "TemperatureCelsius"))
