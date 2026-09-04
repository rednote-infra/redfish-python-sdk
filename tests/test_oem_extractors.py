"""
Unit tests for the OEM extractor strategy package.

Covers every vendor extractor's fan-speed-ratio and drive-temperature
readings against representative payloads observed in the ocme-parent-new
Go monitor and in the previously captured BMC dumps.
"""
from __future__ import annotations

import pytest

from redfish_sdk.managers.oem_extractors import (
    GenericOemExtractor,
    H3cOemExtractor,
    InspurOemExtractor,
    LenovoOemExtractor,
    NettrixOemExtractor,
    OemExtractorRegistry,
    XFusionOemExtractor,
    ZteOemExtractor,
)
from redfish_sdk.models.drive import Drive
from redfish_sdk.models.thermal import Fan


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _fan(**kwargs) -> Fan:
    """Build a Fan from ``@odata.id`` / MemberId + arbitrary extra keys."""
    data = {"@odata.id": "/redfish/v1/Chassis/1/Thermal#/Fans/0",
            "MemberId": "0", "Name": "Fan1"}
    data.update(kwargs)
    return Fan.model_validate(data)


def _drive(**kwargs) -> Drive:
    """Build a Drive from ``@odata.id`` / Id + arbitrary extra keys."""
    data = {"@odata.id": "/redfish/v1/Chassis/1/Drives/0",
            "Id": "0", "Name": "Drive0"}
    data.update(kwargs)
    return Drive.model_validate(data)


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------


class TestOemExtractorRegistry:
    def test_lookup_returns_registered_extractor(self):
        assert isinstance(
            OemExtractorRegistry.get("xfusion"), XFusionOemExtractor
        )
        assert isinstance(
            OemExtractorRegistry.get("XFusion"), XFusionOemExtractor
        )  # case-insensitive
        assert isinstance(OemExtractorRegistry.get("inspur"), InspurOemExtractor)
        assert isinstance(OemExtractorRegistry.get("lenovo"), LenovoOemExtractor)
        assert isinstance(OemExtractorRegistry.get("nettrix"), NettrixOemExtractor)
        assert isinstance(OemExtractorRegistry.get("h3c"), H3cOemExtractor)
        assert isinstance(OemExtractorRegistry.get("zte"), ZteOemExtractor)

    def test_unknown_vendor_falls_back_to_generic(self):
        assert isinstance(
            OemExtractorRegistry.get("no-such-vendor"), GenericOemExtractor
        )

    def test_registered_vendors_covers_all(self):
        registered = set(OemExtractorRegistry.registered_vendors())
        assert {"generic", "xfusion", "inspur", "lenovo",
                "nettrix", "h3c", "zte"} <= registered


# ----------------------------------------------------------------------
# Generic (DMTF fallback)
# ----------------------------------------------------------------------


class TestGenericExtractor:
    def test_fan_ratio_from_reading_and_max(self):
        fan = _fan(Reading=8000, MaxReadingRange=20000)
        assert GenericOemExtractor().get_fan_speed_ratio(fan) == 40.0

    def test_fan_ratio_none_when_reading_missing(self):
        fan = _fan(MaxReadingRange=20000)
        assert GenericOemExtractor().get_fan_speed_ratio(fan) is None

    def test_fan_ratio_none_when_max_zero(self):
        fan = _fan(Reading=8000, MaxReadingRange=0)
        assert GenericOemExtractor().get_fan_speed_ratio(fan) is None

    def test_drive_temperature_none_by_default(self):
        drive = _drive(Oem={"Public": {"TemperatureCelsius": "40"}})
        # Generic doesn't know where the vendor puts it.
        assert GenericOemExtractor().get_drive_temperature_celsius(drive) is None


# ----------------------------------------------------------------------
# xFusion (超聚变)
# ----------------------------------------------------------------------


class TestXFusionExtractor:
    def test_fan_ratio_from_xfusion_key(self):
        fan = _fan(Reading=8000, Oem={"xFusion": {"SpeedRatio": 80}})
        assert XFusionOemExtractor().get_fan_speed_ratio(fan) == 80.0

    def test_fan_ratio_none_when_missing(self):
        fan = _fan(Reading=8000, Oem={"Public": {"SpeedRatio": 65}})
        # xFusion strategy does NOT fall back to Public — that's a design
        # choice: a vendor-specific extractor speaks only its own dialect.
        assert XFusionOemExtractor().get_fan_speed_ratio(fan) is None

    def test_drive_temperature_from_xfusion_key(self):
        drive = _drive(Oem={"xFusion": {"TemperatureCelsius": "35"}})
        assert XFusionOemExtractor().get_drive_temperature_celsius(drive) == 35.0

    def test_drive_temperature_accepts_numeric_and_string(self):
        drive = _drive(Oem={"xFusion": {"TemperatureCelsius": 42}})
        assert XFusionOemExtractor().get_drive_temperature_celsius(drive) == 42.0


# ----------------------------------------------------------------------
# Inspur (浪潮 / IEIT_SYSTEMS)
# ----------------------------------------------------------------------


class TestInspurExtractor:
    def test_fan_ratio_prefers_goem_customestring(self):
        fan = _fan(Oem={
            "gOemCustomeString": {"SpeedRatio": 70},
            "Public": {"SpeedRatio": 55},
        })
        assert InspurOemExtractor().get_fan_speed_ratio(fan) == 70.0

    def test_fan_ratio_falls_back_to_public_when_goem_zero(self):
        # Observed on some Inspur BMCs: gOemCustomeString.SpeedRatio == 0
        # while the actual reading lives under Public. ocme's Go code
        # matches this same fallback exactly.
        fan = _fan(Oem={
            "gOemCustomeString": {"SpeedRatio": 0},
            "Public": {"SpeedRatio": 55},
        })
        assert InspurOemExtractor().get_fan_speed_ratio(fan) == 55.0

    def test_fan_ratio_falls_back_to_public_when_goem_missing(self):
        fan = _fan(Oem={"Public": {"SpeedRatio": 65}})
        assert InspurOemExtractor().get_fan_speed_ratio(fan) == 65.0

    def test_fan_ratio_none_when_both_missing(self):
        fan = _fan(Reading=8000)  # no Oem
        assert InspurOemExtractor().get_fan_speed_ratio(fan) is None

    def test_drive_temperature_from_lowercase_public_temperature(self):
        drive = _drive(Oem={"Public": {"temperature": 33}})
        assert InspurOemExtractor().get_drive_temperature_celsius(drive) == 33.0

    def test_drive_temperature_ignores_pascal_case_key(self):
        # PascalCase TemperatureCelsius is H3C/ZTE's dialect; Inspur
        # must not misread it.
        drive = _drive(Oem={"Public": {"TemperatureCelsius": "40"}})
        assert InspurOemExtractor().get_drive_temperature_celsius(drive) is None


# ----------------------------------------------------------------------
# Lenovo (联想)
# ----------------------------------------------------------------------


class TestLenovoExtractor:
    def test_fan_ratio_derived_from_reading_and_max(self):
        # Lenovo BMCs don't publish an OEM SpeedRatio; fall through to
        # the base derivation.
        fan = _fan(Reading=5000, MaxReadingRange=25000)
        assert LenovoOemExtractor().get_fan_speed_ratio(fan) == 20.0

    def test_drive_temperature_from_lowercase_public_temperature(self):
        drive = _drive(Oem={"Public": {"temperature": 28}})
        assert LenovoOemExtractor().get_drive_temperature_celsius(drive) == 28.0

    def test_drive_temperature_ignores_pascal_case_key(self):
        drive = _drive(Oem={"Public": {"TemperatureCelsius": "40"}})
        assert LenovoOemExtractor().get_drive_temperature_celsius(drive) is None


# ----------------------------------------------------------------------
# Nettrix (宁畅 / Suma)
# ----------------------------------------------------------------------


class TestNettrixExtractor:
    def test_fan_ratio_prefers_public_speed_ratio(self):
        fan = _fan(Reading=8000, MaxReadingRange=20000,
                   Oem={"Public": {"SpeedRatio": 65}})
        assert NettrixOemExtractor().get_fan_speed_ratio(fan) == 65.0

    def test_fan_ratio_falls_back_to_reading_ratio(self):
        fan = _fan(Reading=8000, MaxReadingRange=20000)
        assert NettrixOemExtractor().get_fan_speed_ratio(fan) == 40.0

    def test_drive_temperature_from_top_level_field(self):
        drive = _drive(DiskTemperatureCelsius=29)
        assert NettrixOemExtractor().get_drive_temperature_celsius(drive) == 29.0

    def test_drive_temperature_accepts_string(self):
        drive = _drive(DiskTemperatureCelsius="30.5")
        assert NettrixOemExtractor().get_drive_temperature_celsius(drive) == 30.5

    def test_drive_temperature_none_when_missing(self):
        drive = _drive(Oem={"Public": {"TemperatureCelsius": "40"}})
        assert NettrixOemExtractor().get_drive_temperature_celsius(drive) is None


# ----------------------------------------------------------------------
# H3C (新华三)
# ----------------------------------------------------------------------


class TestH3cExtractor:
    def test_fan_ratio_from_public_speed_ratio(self):
        fan = _fan(Oem={"Public": {"SpeedRatio": 65}})
        assert H3cOemExtractor().get_fan_speed_ratio(fan) == 65.0

    def test_fan_ratio_none_when_missing(self):
        fan = _fan(Reading=8000)  # no Oem at all
        assert H3cOemExtractor().get_fan_speed_ratio(fan) is None

    def test_drive_temperature_from_pascal_case_key(self):
        drive = _drive(Oem={"Public": {"TemperatureCelsius": "40"}})
        assert H3cOemExtractor().get_drive_temperature_celsius(drive) == 40.0

    def test_drive_temperature_ignores_lowercase_key(self):
        drive = _drive(Oem={"Public": {"temperature": 33}})
        assert H3cOemExtractor().get_drive_temperature_celsius(drive) is None


# ----------------------------------------------------------------------
# ZTE (中兴)
# ----------------------------------------------------------------------


class TestZteExtractor:
    def test_fan_ratio_from_public_speed_ratio(self):
        fan = _fan(Oem={"Public": {"SpeedRatio": 72}})
        assert ZteOemExtractor().get_fan_speed_ratio(fan) == 72.0

    def test_drive_temperature_from_pascal_case_key(self):
        drive = _drive(Oem={"Public": {"TemperatureCelsius": 45}})
        assert ZteOemExtractor().get_drive_temperature_celsius(drive) == 45.0


# ----------------------------------------------------------------------
# Cross-vendor: verify each extractor stays isolated when a payload
# contains multiple vendor sub-keys.
# ----------------------------------------------------------------------


class TestCrossVendorIsolation:
    """
    A single Fan/Drive payload may contain both Public and vendor-specific
    Oem keys (observed in the wild — some BMCs mirror common metadata to
    Public while still populating their own key). Each extractor must
    read only its own dialect.
    """

    def test_xfusion_ignores_public_speed_ratio(self):
        fan = _fan(Oem={
            "Public": {"SpeedRatio": 55},
            "xFusion": {"SpeedRatio": 80},
        })
        assert XFusionOemExtractor().get_fan_speed_ratio(fan) == 80.0

    def test_h3c_ignores_xfusion_temperature(self):
        drive = _drive(Oem={
            "Public": {"TemperatureCelsius": "40"},
            "xFusion": {"TemperatureCelsius": "99"},
        })
        # H3C reads Public.TemperatureCelsius, NOT xFusion.
        assert H3cOemExtractor().get_drive_temperature_celsius(drive) == 40.0

    def test_inspur_lowercase_vs_pascal_case_isolation(self):
        drive = _drive(Oem={"Public": {
            "temperature": 33,
            "TemperatureCelsius": "99",
        }})
        # Inspur reads lowercase 'temperature', not the PascalCase alias.
        assert InspurOemExtractor().get_drive_temperature_celsius(drive) == 33.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
