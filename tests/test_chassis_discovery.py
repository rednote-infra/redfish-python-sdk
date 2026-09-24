"""Tests for dynamically discovering the default Chassis member."""
from __future__ import annotations

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishNotFoundError
from redfish_sdk.models.chassis import Chassis, Thermal
from redfish_sdk.models.common import Link
from redfish_sdk.models.root import RootService
from redfish_sdk.models.thermal import Fan


def _client_with_self_chassis(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    root = RootService.model_construct(
        chassis=Link.model_construct(odata_id="/redfish/v1/Chassis")
    )
    chassis = Chassis.model_construct(
        odata_id="/redfish/v1/Chassis/Self",
        thermal=Link.model_construct(odata_id="/redfish/v1/Chassis/Self/Thermal"),
    )
    requests = []

    monkeypatch.setattr(client, "_get_root", lambda: root)

    def fake_get_raw(path):
        requests.append(path)
        assert path != "/redfish/v1/Chassis/1"
        assert path == "/redfish/v1/Chassis"
        return {"Members": [{"@odata.id": "/redfish/v1/Chassis/Self"}]}

    def fake_get(path, model_class):
        requests.append(path)
        if path == "/redfish/v1/Chassis/1":
            raise RedfishNotFoundError(path)
        if path == "/redfish/v1/Chassis/Self":
            return chassis
        if path == "/redfish/v1/Chassis/Self/Thermal":
            return Thermal.model_construct(odata_id=path)
        raise AssertionError(f"unexpected request: {path}")

    monkeypatch.setattr(client._http_client, "get_raw", fake_get_raw)
    monkeypatch.setattr(client._http_client, "get", fake_get)
    return client, requests


def test_get_chassis_falls_back_to_self_when_default_member_is_missing(monkeypatch):
    client, requests = _client_with_self_chassis(monkeypatch)

    chassis = client.get_chassis()

    assert chassis.odata_id == "/redfish/v1/Chassis/Self"
    assert requests == [
        "/redfish/v1/Chassis/1",
        "/redfish/v1/Chassis",
        "/redfish/v1/Chassis/Self",
    ]
    client.close()


def test_get_thermal_uses_the_discovered_chassis_link(monkeypatch):
    client, requests = _client_with_self_chassis(monkeypatch)

    thermal = client.get_thermal()

    assert thermal.odata_id == "/redfish/v1/Chassis/Self/Thermal"
    assert requests == [
        "/redfish/v1/Chassis/1",
        "/redfish/v1/Chassis",
        "/redfish/v1/Chassis/Self",
        "/redfish/v1/Chassis/Self/Thermal",
    ]
    client.close()


def test_get_fan_derives_its_path_from_the_discovered_chassis(monkeypatch):
    client, requests = _client_with_self_chassis(monkeypatch)
    fan_path = "/redfish/v1/Chassis/Self/ThermalSubsystem/Fans/0"

    def fake_get_raw(path):
        requests.append(path)
        if path == "/redfish/v1/Chassis":
            return {"Members": [{"@odata.id": "/redfish/v1/Chassis/Self"}]}
        if path == "/redfish/v1/Chassis/Self/ThermalSubsystem/Fans":
            return {"Members": [{"@odata.id": fan_path}]}
        if path == fan_path:
            return {
                "@odata.id": fan_path,
                "Name": "Fan 1",
                "Reading": 6000,
                "ReadingUnits": "RPM",
            }
        raise AssertionError(f"unexpected request: {path}")

    monkeypatch.setattr(client._http_client, "get_raw", fake_get_raw)

    fans = client.get_fan()

    assert len(fans) == 1
    assert isinstance(fans[0], Fan)
    assert fans[0].odata_id == fan_path
    assert requests == [
        "/redfish/v1/Chassis/1",
        "/redfish/v1/Chassis",
        "/redfish/v1/Chassis/Self",
        "/redfish/v1/Chassis/Self/ThermalSubsystem/Fans",
        fan_path,
    ]
    client.close()


def test_get_chassis_preserves_an_explicit_identifier(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    root = RootService.model_construct(
        chassis=Link.model_construct(odata_id="/redfish/v1/Chassis")
    )
    monkeypatch.setattr(client, "_get_root", lambda: root)

    def fake_get(path, model_class):
        assert path == "/redfish/v1/Chassis/Custom"
        return Chassis.model_construct(odata_id=path)

    monkeypatch.setattr(client._http_client, "get", fake_get)

    chassis = client.get_chassis("Custom")

    assert chassis.odata_id == "/redfish/v1/Chassis/Custom"
    client.close()


def test_get_chassis_uses_one_when_none_is_passed(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    root = RootService.model_construct(
        chassis=Link.model_construct(odata_id="/redfish/v1/Chassis")
    )
    monkeypatch.setattr(client, "_get_root", lambda: root)

    def fake_get(path, model_class):
        assert path == "/redfish/v1/Chassis/1"
        return Chassis.model_construct(odata_id=path)

    monkeypatch.setattr(client._http_client, "get", fake_get)

    chassis = client.get_chassis(None)

    assert chassis.odata_id == "/redfish/v1/Chassis/1"
    client.close()
