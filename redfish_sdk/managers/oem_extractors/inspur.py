"""
Inspur (浪潮 / IEIT_SYSTEMS) OEM extractor.

Inspur BMCs publish fan speed under two possible OEM sub-keys and drive
temperature under a lowercase field name inside ``Public``:

    Fan.Oem.gOemCustomeString.SpeedRatio   (preferred; note: the typo
                                            "Customestring" is from the
                                            BMC firmware itself)
    Fan.Oem.Public.SpeedRatio              (fallback when the former is
                                            absent or reported as 0)
    Drive.Oem.Public.temperature           (lowercase key, Celsius)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .base import (
    BaseOemExtractor,
    read_public_field,
    read_vendor_field,
    to_float,
)

if TYPE_CHECKING:
    from ...models.drive import Drive
    from ...models.thermal import Fan


class InspurOemExtractor(BaseOemExtractor):
    """OEM field extractor for Inspur (浪潮) servers."""

    def get_fan_speed_ratio(self, fan: "Fan") -> Optional[float]:
        # gOemCustomeString wins; fall back to Public when it's missing
        # or explicitly reported as 0 (some Inspur BMCs zero-fill the
        # OEM slot while the actual reading lives under Public).
        primary = to_float(
            read_vendor_field(fan.oem, "gOemCustomeString", "SpeedRatio")
        )
        if primary is not None and primary != 0:
            return primary
        fallback = to_float(read_public_field(fan.oem, "SpeedRatio"))
        return fallback if fallback is not None else primary

    def get_drive_temperature_celsius(self, drive: "Drive") -> Optional[float]:
        # Note: lowercase 'temperature'. The PascalCase
        # ``TemperatureCelsius`` alias must NOT match this reading —
        # :func:`read_public_field` matches by exact alias so the two
        # keys stay isolated.
        return to_float(read_public_field(drive.oem, "temperature"))
