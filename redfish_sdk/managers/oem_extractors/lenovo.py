"""
Lenovo (联想) OEM extractor.

Lenovo BMCs do not publish an OEM ``SpeedRatio``; the fan speed
percentage is derived from ``Reading / MaxReadingRange`` (handled by
:class:`BaseOemExtractor`). Drive temperature is exposed under
``Public`` with the lowercase key ``temperature``:

    Drive.Oem.Public.temperature   (lowercase key, Celsius)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .base import BaseOemExtractor, read_public_field, to_float

if TYPE_CHECKING:
    from ...models.drive import Drive


class LenovoOemExtractor(BaseOemExtractor):
    """OEM field extractor for Lenovo (联想) servers."""

    # get_fan_speed_ratio: falls back to the base Reading/MaxReadingRange
    # derivation — Lenovo BMCs do not publish an OEM SpeedRatio.

    def get_drive_temperature_celsius(self, drive: "Drive") -> Optional[float]:
        return to_float(read_public_field(drive.oem, "temperature"))
