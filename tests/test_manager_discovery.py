"""Tests for dynamically discovering the default Manager member."""
from __future__ import annotations

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishNotFoundError
from redfish_sdk.models.common import Link
from redfish_sdk.models.managers import Manager, NetworkProtocol
from redfish_sdk.models.root import RootService
from redfish_sdk.models.systems import System


def _client_with_self_manager(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    root = RootService.model_construct(
        managers=Link.model_construct(odata_id="/redfish/v1/Managers")
    )
    manager = Manager.model_construct(odata_id="/redfish/v1/Managers/Self")
    requests = []

    monkeypatch.setattr(client, "_get_root", lambda: root)

    def fake_get_raw(path):
        requests.append(path)
        assert path != "/redfish/v1/Managers/1"
        assert path == "/redfish/v1/Managers"
        return {"Members": [{"@odata.id": "/redfish/v1/Managers/Self"}]}

    def fake_get(path, model_class):
        requests.append(path)
        if path == "/redfish/v1/Managers/1":
            raise RedfishNotFoundError(path)
        if path == "/redfish/v1/Managers/Self":
            return manager
        if path == "/redfish/v1/Managers/Self/NetworkProtocol":
            return NetworkProtocol.model_construct(odata_id=path)
        raise AssertionError(f"unexpected request: {path}")

    monkeypatch.setattr(client._http_client, "get_raw", fake_get_raw)
    monkeypatch.setattr(client._http_client, "get", fake_get)
    return client, requests


def test_get_manager_falls_back_to_self_when_default_member_is_missing(monkeypatch):
    client, requests = _client_with_self_manager(monkeypatch)

    manager = client.get_manager()

    assert manager.odata_id == "/redfish/v1/Managers/Self"
    assert requests == [
        "/redfish/v1/Managers/1",
        "/redfish/v1/Managers",
        "/redfish/v1/Managers/Self",
    ]
    client.close()


def test_get_network_protocol_uses_the_discovered_manager_link(monkeypatch):
    client, requests = _client_with_self_manager(monkeypatch)

    protocol = client.get_network_protocol()

    assert protocol.odata_id == "/redfish/v1/Managers/Self/NetworkProtocol"
    assert requests == [
        "/redfish/v1/Managers/1",
        "/redfish/v1/Managers",
        "/redfish/v1/Managers/Self",
        "/redfish/v1/Managers/Self/NetworkProtocol",
    ]
    client.close()


def test_get_manager_preserves_an_explicit_identifier(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    root = RootService.model_construct(
        managers=Link.model_construct(odata_id="/redfish/v1/Managers")
    )
    monkeypatch.setattr(client, "_get_root", lambda: root)

    def fake_get(path, model_class):
        assert path == "/redfish/v1/Managers/Custom"
        return Manager.model_construct(odata_id=path)

    monkeypatch.setattr(client._http_client, "get", fake_get)

    manager = client.get_manager("Custom")

    assert manager.odata_id == "/redfish/v1/Managers/Custom"
    client.close()


def test_get_manager_uses_one_when_none_is_passed(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    root = RootService.model_construct(
        managers=Link.model_construct(odata_id="/redfish/v1/Managers")
    )
    monkeypatch.setattr(client, "_get_root", lambda: root)

    def fake_get(path, model_class):
        assert path == "/redfish/v1/Managers/1"
        return Manager.model_construct(odata_id=path)

    monkeypatch.setattr(client._http_client, "get", fake_get)

    manager = client.get_manager(None)

    assert manager.odata_id == "/redfish/v1/Managers/1"
    client.close()


def test_get_gpus_uses_default_system_id_when_omitted(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    requested_system_ids = []
    system = System.model_construct(odata_id="/redfish/v1/Systems/Self")

    def fake_get(system_id=None):
        requested_system_ids.append(system_id)
        return system

    monkeypatch.setattr(client._systems, "get", fake_get)
    monkeypatch.setattr(client, "_get_chassis_collection", lambda: [])

    assert client.get_gpus() == []
    assert requested_system_ids == ["1"]
    client.close()
