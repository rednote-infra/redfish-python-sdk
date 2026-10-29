"""Capability-aware drive identification tests."""

import json
from pathlib import Path

import pytest

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishValidationError
from redfish_sdk.models.drive import Drive

TESTDATA_DIR = Path(__file__).parent.parent / "testdata"
DRIVE_PATH = "/redfish/v1/Chassis/Self/Drives/NVMe0"


def _fixtures() -> dict:
    with (TESTDATA_DIR / "drive_identification.json").open(
        encoding="utf-8"
    ) as fixture:
        return json.load(fixture)


def _client_with_drives(monkeypatch, *payloads):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    drives = iter(Drive.model_validate(payload) for payload in payloads)
    calls = []

    def get(path, model):
        calls.append(("GET", path))
        assert model is Drive
        client._http_client._last_etag[path] = '"drive-etag"'
        return next(drives)

    def patch_raw(path, body, extra_headers=None):
        calls.append(("PATCH", path, body, client._http_client._last_etag[path]))

    monkeypatch.setattr(client._http_client, "get", get)
    monkeypatch.setattr(client._http_client, "patch_raw", patch_raw)
    return client, calls


def test_drive_models_location_indicator_and_legacy_view():
    drive = Drive.model_validate(_fixtures()["ModernOnlyOff"])

    assert drive.location_indicator_active is False
    assert drive.indicator_led == "Off"
    assert "location_indicator_active" in drive.model_fields_set
    assert "indicator_led" not in drive.model_fields_set


def test_modern_location_indicator_is_patched(monkeypatch):
    fixtures = _fixtures()
    client, calls = _client_with_drives(
        monkeypatch,
        fixtures["ModernOnlyOff"],
        fixtures["ModernOnlyOn"],
    )

    assert client.set_drive_location_indicator(DRIVE_PATH, True) is True
    assert calls == [
        ("GET", DRIVE_PATH),
        ("PATCH", DRIVE_PATH, {"LocationIndicatorActive": True}, '"drive-etag"'),
        ("GET", DRIVE_PATH),
    ]
    client.close()


def test_legacy_indicator_is_used_as_fallback(monkeypatch):
    fixtures = _fixtures()
    client, calls = _client_with_drives(
        monkeypatch,
        fixtures["LegacyOnlyOff"],
        fixtures["LegacyOnlyOn"],
    )

    assert client.set_drive_location_indicator(DRIVE_PATH, True) is True
    assert calls[1][2] == {"IndicatorLED": "Lit"}
    client.close()


def test_modern_indicator_is_preferred_when_both_are_advertised(monkeypatch):
    fixtures = _fixtures()
    client, calls = _client_with_drives(
        monkeypatch,
        fixtures["BothOff"],
        fixtures["BothModernOn"],
    )

    assert client.set_drive_location_indicator(DRIVE_PATH, True) is True
    assert calls[1][2] == {"LocationIndicatorActive": True}
    client.close()


def test_unsupported_drive_is_not_patched(monkeypatch):
    client, calls = _client_with_drives(monkeypatch, _fixtures()["Unsupported"])

    with pytest.raises(
        RedfishValidationError,
        match="does not advertise LocationIndicatorActive or IndicatorLED",
    ):
        client.set_drive_location_indicator(DRIVE_PATH, True)

    assert calls == [("GET", DRIVE_PATH)]
    client.close()


def test_legacy_helper_translates_modern_only_lit_and_off(monkeypatch):
    fixtures = _fixtures()
    client, calls = _client_with_drives(
        monkeypatch,
        fixtures["ModernOnlyOff"],
        fixtures["ModernOnlyOn"],
        fixtures["ModernOnlyOn"],
        fixtures["ModernOnlyOff"],
    )

    assert client.set_drive_indicator_led(DRIVE_PATH, "Lit") == "Lit"
    assert client.set_drive_indicator_led(DRIVE_PATH, "Off") == "Off"
    assert calls[1][2] == {"LocationIndicatorActive": True}
    assert calls[4][2] == {"LocationIndicatorActive": False}
    client.close()


def test_legacy_helper_preserves_indicator_led_payload(monkeypatch):
    fixtures = _fixtures()
    client, calls = _client_with_drives(
        monkeypatch,
        fixtures["LegacyOnlyOff"],
        fixtures["LegacyOnlyOn"],
    )

    assert client.set_drive_indicator_led(DRIVE_PATH, "Lit") == "Lit"
    assert calls[1][2] == {"IndicatorLED": "Lit"}
    client.close()
