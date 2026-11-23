"""Vendor-specific inlet history routing without real BMC requests."""
from unittest.mock import Mock

import pytest

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishAuthError, RedfishException, RedfishNotFoundError
from redfish_sdk.managers.oem_extractors import BaseOemExtractor
from redfish_sdk.models.thermal import InletHistoryTemperature, Thermal
from redfish_sdk.oem import OemCategory, OemProviderRegistry

THERMAL_URI = "/redfish/v1/Chassis/Self/Thermal"
LEGACY_URI = "/redfish/v1/Chassis/Self/Thermal/InletHistoryTemperature"
AMI_URI = "/redfish/v1/Chassis/Self/Thermal/Oem/Ami/InletHistoryTemperature"


@pytest.fixture
def client(monkeypatch):
    with RedfishClient(
        "example.test", "test", "test", verify_ssl=True,
        oem_providers=OemProviderRegistry(discover=False),
    ) as instance:
        monkeypatch.setattr(instance, "get_system", Mock(side_effect=AssertionError("Unexpected System request")))
        yield instance


def install_thermal(client, monkeypatch, **fields):
    thermal = Thermal.model_validate({"@odata.id": THERMAL_URI, **fields})
    read = Mock(return_value=thermal)
    monkeypatch.setattr(client._chassis, "thermal", read)
    result = InletHistoryTemperature.model_validate({
        "@odata.id": AMI_URI,
        "HistoricalInletTemp": [{"avg": 20.0, "max": 22.0, "min": 18.0, "time": "2026-11-17T10:00:00Z"}],
    })
    get = Mock(return_value=result)
    monkeypatch.setattr(client._http_client, "get", get)
    return thermal, read, get, result


@pytest.mark.parametrize("oem", [{}, {"Other": {}}, {"Other": {"Ami": {}}}])
def test_default_uses_advertised_link(client, monkeypatch, oem):
    _, read, get, result = install_thermal(
        client, monkeypatch, Oem=oem,
        InletHistoryTemperature={"@odata.id": LEGACY_URI},
    )
    assert client.get_inlet_history_temperature("Self") is result
    read.assert_called_once_with("Self")
    get.assert_called_once_with(LEGACY_URI, InletHistoryTemperature)


def test_default_without_link_does_not_probe_ami(client, monkeypatch):
    _, _, get, _ = install_thermal(client, monkeypatch)
    assert client.get_inlet_history_temperature("Self") is None
    get.assert_not_called()


def test_ami_is_detected_from_thermal_oem(client, monkeypatch):
    _, _, get, result = install_thermal(client, monkeypatch, Oem={"Ami": {}})
    assert client.get_inlet_history_temperature("Self") is result
    get.assert_called_once_with(AMI_URI, InletHistoryTemperature)
    assert result.historical_inlet_temp[0].avg == 20.0


def test_explicit_ami_does_not_require_an_oem_link(client, monkeypatch):
    client.oem_vendor = "ami"
    _, _, get, result = install_thermal(client, monkeypatch)
    assert client.get_inlet_history_temperature("Self") is result
    get.assert_called_once_with(AMI_URI, InletHistoryTemperature)


@pytest.mark.parametrize("vendor", ["generic", "xfusion", "lenovo", "unknown-vendor"])
def test_explicit_vendor_overrides_ami_detection(client, monkeypatch, vendor):
    client.oem_vendor = vendor
    _, _, get, result = install_thermal(
        client, monkeypatch, Oem={"Ami": {}},
        InletHistoryTemperature={"@odata.id": LEGACY_URI},
    )
    assert client.get_inlet_history_temperature("Self") is result
    get.assert_called_once_with(LEGACY_URI, InletHistoryTemperature)


@pytest.mark.parametrize("thermal_uri", ["/custom/redfish/v1/Chassis/Enclosure/Thermal", THERMAL_URI + "/"])
def test_ami_uses_actual_thermal_uri(client, monkeypatch, thermal_uri):
    _, _, get, result = install_thermal(client, monkeypatch, **{"@odata.id": thermal_uri, "Oem": {"Ami": {}}})
    assert client.get_inlet_history_temperature("Self") is result
    get.assert_called_once_with(thermal_uri.rstrip("/") + "/Oem/Ami/InletHistoryTemperature", InletHistoryTemperature)


def test_ami_without_thermal_identity_does_not_guess_chassis_one(client, monkeypatch):
    _, _, get, _ = install_thermal(client, monkeypatch, **{"@odata.id": None, "Oem": {"Ami": {}}})
    assert client.get_inlet_history_temperature("Self") is None
    get.assert_not_called()


@pytest.mark.parametrize("vendor,oem,expected", [
    (None, {}, LEGACY_URI),
    ("ami", {}, AMI_URI),
    (None, {"Ami": {}}, AMI_URI),
])
def test_history_404_returns_none_without_probing(client, monkeypatch, vendor, oem, expected):
    client.oem_vendor = vendor
    _, _, get, _ = install_thermal(
        client, monkeypatch, Oem=oem,
        InletHistoryTemperature={"@odata.id": LEGACY_URI},
    )
    get.side_effect = RedfishNotFoundError(expected)
    assert client.get_inlet_history_temperature("Self") is None
    get.assert_called_once_with(expected, InletHistoryTemperature)


@pytest.mark.parametrize("error", [RedfishAuthError(401), RedfishException(500, "Upstream failure")])
@pytest.mark.parametrize("vendor", ["generic", "ami"])
def test_non_404_errors_propagate_unchanged(client, monkeypatch, vendor, error):
    client.oem_vendor = vendor
    _, _, get, _ = install_thermal(
        client, monkeypatch, InletHistoryTemperature={"@odata.id": LEGACY_URI},
    )
    get.side_effect = error
    with pytest.raises(type(error)) as caught:
        client.get_inlet_history_temperature("Self")
    assert caught.value is error


def test_thermal_fetch_errors_propagate(client, monkeypatch):
    error = RedfishNotFoundError(THERMAL_URI)
    monkeypatch.setattr(client._chassis, "thermal", Mock(side_effect=error))
    with pytest.raises(RedfishNotFoundError) as caught:
        client.get_inlet_history_temperature("Self")
    assert caught.value is error


def test_client_scoped_vendor_strategy_is_used(client, monkeypatch):
    class CustomExtractor(BaseOemExtractor):
        def get_inlet_history_temperature_uri(self, thermal):
            return "/custom/history"

    client.oem_vendor = "custom"
    client.oem_providers.register(OemCategory.EXTRACTOR, "custom", CustomExtractor())
    _, _, get, result = install_thermal(client, monkeypatch)
    assert client.get_inlet_history_temperature("Self") is result
    get.assert_called_once_with("/custom/history", InletHistoryTemperature)
