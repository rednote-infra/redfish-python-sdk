"""
Nettrix (宁畅 / Suma) OEM extractor.

Nettrix BMCs publish drive temperature as a *top-level* field on the
Drive resource (not under ``Oem``); fan speed prefers the standard
``Public.SpeedRatio`` and otherwise falls back to the
``Reading / MaxReadingRange`` derivation:

    Fan.Oem.Public.SpeedRatio           (preferred)
    Fan.Reading / Fan.MaxReadingRange   (fallback, via base class)
    Drive.DiskTemperatureCelsius        (top-level, numeric string)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .base import BaseOemExtractor, read_public_field, to_float

if TYPE_CHECKING:
    from ...models.drive import Drive
    from ...models.thermal import Fan


class NettrixOemExtractor(BaseOemExtractor):
    """OEM field extractor for Nettrix (宁畅) servers."""

    def get_fan_speed_ratio(self, fan: "Fan") -> Optional[float]:
        public_ratio = to_float(read_public_field(fan.oem, "SpeedRatio"))
        if public_ratio is not None and public_ratio != 0:
            return public_ratio
        # No usable OEM reading — derive from Reading / MaxReadingRange.
        return super().get_fan_speed_ratio(fan)

    def get_drive_temperature_celsius(self, drive: "Drive") -> Optional[float]:
        # Nettrix exposes this at the top level, not under Oem.
        return to_float(drive.disk_temperature_celsius)
