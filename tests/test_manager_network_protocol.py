"""Tests for DMTF-standard ManagerNetworkProtocol helpers."""
from __future__ import annotations

from redfish_sdk import RedfishClient
from redfish_sdk.models.common import Collection, Link
from redfish_sdk.models.managers import NetworkProtocol


def test_get_https_certificates_uses_standard_network_protocol_link(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    protocol = NetworkProtocol.model_validate(
        {
            "HTTPS": {
                "Certificates": {
                    "@odata.id": "/redfish/v1/CertificateService/Certificates"
                }
            }
        }
    )
    expected = Collection[Link].model_validate(
        {"Members": [{"@odata.id": "/redfish/v1/CertificateService/Certificates/1"}]}
    )
    monkeypatch.setattr(client._managers, "network_protocol", lambda manager_id="1": protocol)

    def fake_get(path, model_class):
        assert path == "/redfish/v1/CertificateService/Certificates"
        assert model_class == Collection[Link]
        return expected

    monkeypatch.setattr(client._http_client, "get", fake_get)

    certificates = client.get_https_certificates()

    assert certificates.members[0].odata_id.endswith("/1")
    client.close()
