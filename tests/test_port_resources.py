"""Standard Port discovery and actions remain distinct from legacy NetworkPort."""

from __future__ import annotations

import pytest

from redfish_sdk import Port, RedfishClient
from redfish_sdk.exceptions import (
    RedfishException,
    RedfishNotFoundError,
    RedfishValidationError,
)
from redfish_sdk.models.common import RedfishResponse
from redfish_sdk.models.fabric import PortMetrics, ResetTransceiversRequest
from redfish_sdk.models.system_resources import NetworkPort


@pytest.fixture
def port_client(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    owner = "/custom/fabric-adapters/FA-1"
    ports_only_owner = {
        "Id": "FA-1",
        "@odata.id": owner,
        "Ports": {"@odata.id": "/custom/inventory/standard-port-index"},
    }
    network_ports_only_owner = {
        "Id": "legacy-nic",
        "@odata.id": "/custom/network-adapters/legacy",
        "NetworkPorts": {"@odata.id": "/custom/inventory/legacy-port-index"},
    }
    collection = {
        "Members": [
            {"@odata.id": "/custom/members/alpha"},
            {"@odata.id": "/custom/members/not-a-port-shaped-uri"},
        ]
    }
    payloads = {
        "/custom/members/alpha": {
            "@odata.type": "#Port.v1_20_0.Port",
            "@odata.id": "/custom/members/alpha",
            "@odata.etag": 'W/"port-alpha"',
            "Id": "alpha",
            "PortProtocol": "Ethernet",
            "LinkConfiguration": [
                {
                    "AutoSpeedNegotiationCapable": True,
                    "AutoSpeedNegotiationEnabled": True,
                    "CapableLinkSpeedGbps": [100, 200],
                    "ConfiguredNetworkLinks": [
                        {"ConfiguredLinkSpeedGbps": 200, "ConfiguredWidth": 4}
                    ],
                }
            ],
            "LinkPartnerExpected": {
                "DeviceType": "Switch",
                "LinkPartnerId": "switch-a",
                "PortId": "swp1",
            },
            "LinkPartnerReceived": {
                "DeviceType": "Switch",
                "LinkPartnerId": "switch-a",
                "PortId": "swp1",
            },
            "LinkPartnerValidation": {
                "DeviceCheckEnabled": True,
                "PortCheckEnabled": True,
                "ValidationState": "Success",
            },
            "Metrics": {"@odata.id": "/custom/telemetry/alpha"},
            "Actions": {
                "#Port.ResetTransceivers": {
                    "target": "/custom/actions/reset-alpha"
                }
            },
        },
        "/custom/members/not-a-port-shaped-uri": {
            "@odata.type": "#Port.v1_20_0.Port",
            "@odata.id": "/custom/members/not-a-port-shaped-uri",
            "Id": "beta",
            "PortProtocol": "FutureProtocol",
        },
        "/custom/telemetry/alpha": {
            "@odata.type": "#PortMetrics.v1_9_1.PortMetrics",
            "@odata.id": "/custom/telemetry/alpha",
            "Id": "alpha-metrics",
            "RXBytes": 1000,
            "TXBytes": 2000,
        },
    }
    raw_payloads = {
        owner: ports_only_owner,
        "/custom/network-adapters/modern": {
            "Ports": ports_only_owner["Ports"]
        },
        "/custom/network-interfaces/NI-1": {
            "Ports": ports_only_owner["Ports"]
        },
        "/custom/switches/SW-1": {"Ports": ports_only_owner["Ports"]},
        network_ports_only_owner["@odata.id"]: network_ports_only_owner,
        ports_only_owner["Ports"]["@odata.id"]: collection,
    }
    post_calls = []

    def get_raw(path):
        return raw_payloads[path]

    def get(path, model):
        return model.model_validate(payloads[path])

    def post(path, model, body=None, raw_body=None):
        post_calls.append((path, model, body, raw_body))
        return RedfishResponse.model_construct()

    monkeypatch.setattr(client._http_client, "get_raw", get_raw)
    monkeypatch.setattr(client._http_client, "get", get)
    monkeypatch.setattr(client._http_client, "post", post)
    yield client, owner, network_ports_only_owner["@odata.id"], post_calls
    client.close()


def test_discovers_standard_ports_from_advertised_custom_paths(port_client):
    client, owner, _, _ = port_client

    ports = client.get_ports(owner)

    assert [port.id for port in ports] == ["alpha", "beta"]
    assert ports[0].odata_etag == 'W/"port-alpha"'
    assert ports[0].link_configuration[0].capable_link_speed_gbps == [100, 200]
    assert ports[0].link_partner_expected.link_partner_id == "switch-a"
    assert ports[0].link_partner_validation.validation_state == "Success"
    assert ports[1].port_protocol == "FutureProtocol"
    assert client.get_port("/custom/members/alpha", owner).odata_id == ports[0].odata_id


@pytest.mark.parametrize(
    "owner",
    [
        "/custom/network-adapters/modern",
        "/custom/network-interfaces/NI-1",
        "/custom/switches/SW-1",
    ],
)
def test_same_ports_link_discovery_applies_to_adapter_interface_and_switch(
    port_client, owner
):
    client, _, _, _ = port_client

    assert [port.id for port in client.get_ports(owner)] == ["alpha", "beta"]


def test_networkports_only_owner_does_not_become_standard_port(
    port_client, monkeypatch
):
    client, _, legacy_owner, _ = port_client
    legacy = NetworkPort.model_validate(
        {"Id": "legacy-1", "@odata.id": "/custom/legacy/members/1"}
    )
    monkeypatch.setattr(
        client._system_resources,
        "network_ports",
        lambda network_interface_id=None, system_id=None: [legacy],
    )

    with pytest.raises(RedfishNotFoundError, match="does not advertise Ports"):
        client.get_ports(legacy_owner)

    assert client.get_network_ports() == [legacy]
    assert not isinstance(legacy, Port)


def test_reads_optional_port_metrics_and_rejects_missing_link(port_client):
    client, owner, _, _ = port_client

    metrics = client.get_port_metrics("alpha", owner_odata_id=owner)

    assert isinstance(metrics, PortMetrics)
    assert metrics.rx_bytes == 1000
    with pytest.raises(RedfishNotFoundError, match="does not advertise Metrics"):
        client.get_port_metrics("beta", owner_odata_id=owner)


def test_reset_transceivers_uses_only_advertised_action(port_client):
    client, owner, _, post_calls = port_client

    response = client.reset_port_transceivers("alpha", owner)

    assert isinstance(response, RedfishResponse)
    assert len(post_calls) == 1
    path, model, body, raw_body = post_calls[0]
    assert path == "/custom/actions/reset-alpha"
    assert model is RedfishResponse
    assert isinstance(body, ResetTransceiversRequest)
    assert body.model_dump(by_alias=True) == {}
    assert raw_body is None

    with pytest.raises(RedfishValidationError, match="#Port.ResetTransceivers"):
        client.reset_port_transceivers("beta", owner)


def test_reset_transceivers_preserves_redfish_errors(port_client, monkeypatch):
    client, owner, _, _ = port_client
    failure = RedfishException(503, "reset temporarily unavailable")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(client._http_client, "post", fail)

    with pytest.raises(RedfishException) as exc_info:
        client.reset_port_transceivers("alpha", owner)

    assert exc_info.value is failure
