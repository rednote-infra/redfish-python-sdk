"""Offline coverage for ZTE-shaped and legacy OEM security resources."""
import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishException, RedfishNotFoundError
from redfish_sdk.models.managers import FirewallRules, HttpsCert, Manager

MANAGER = "/redfish/v1/Managers/Example"
SECURITY = f"{MANAGER}/SecurityService"
CERT = "/vendor/certificate"
FIREWALL = "/vendor/firewall"


@pytest.fixture
def client(monkeypatch):
    with RedfishClient(host="example.test", username="test", password="test", verify_ssl=True) as client:
        manager = Manager.model_validate({"Id": "Example", "@odata.id": MANAGER})
        monkeypatch.setattr(client._managers, "get", lambda manager_id=None: manager)
        yield client, manager


def serve(monkeypatch, client, payloads):
    calls = []

    def get(path, model):
        calls.append(path)
        payload = payloads[path]
        if isinstance(payload, Exception):
            raise payload
        return model.model_validate(payload)

    monkeypatch.setattr(client._http_client, "get", get)
    return calls


def certificate_payload():
    return {
        "Id": "HttpsCert", "@odata.id": CERT,
        "X509CertificateInformation": {"ServerCert": {
            "Subject": {"CommonName": "example.test", "Country": "US", "State": "Example",
                        "City": "Example", "Organization": "Example", "OrganizationalUnit": "Test"},
            "Issuer": {"CommonName": "Example CA"},
            "PublicKeyLengthBits": "2048", "CertificateString": None, "CertificateType": None,
            "ValidNotBefore": "Apr 16 15:40:38 2021 GMT",
            "ValidNotAfter": "Apr 14 15:40:38 2031 GMT",
            "SerialNumber": "012345", "KeyUsage": "Digital Signature",
            "SignatureAlgorithm": "sha256WithRSAEncryption",
        }},
    }


def test_zte_certificate_without_manager_oem_link(client, monkeypatch):
    sdk, _ = client
    calls = serve(monkeypatch, sdk, {
        SECURITY: {"Id": "SecurityService", "@odata.id": SECURITY, "HttpsCert": {"@odata.id": CERT}},
        CERT: certificate_payload(),
    })
    result = sdk.get_https_cert()
    cert = result.x509_certificate_information.server_cert
    assert cert.subject.common_name == "example.test"
    assert cert.subject.organizational_unit == "Test"
    assert cert.issuer.common_name == "Example CA"
    assert cert.public_key_length_bits == 2048
    assert cert.valid_not_before == "Apr 16 15:40:38 2021 GMT"
    assert cert.valid_not_after == "Apr 14 15:40:38 2031 GMT"
    assert cert.certificate_string is None and cert.certificate_type is None
    assert cert.serial_number == "012345"
    assert cert.key_usage == "Digital Signature"
    assert cert.signature_algorithm == "sha256WithRSAEncryption"
    assert calls == [SECURITY, CERT]


def test_legacy_links_and_advertised_security_take_precedence(client, monkeypatch):
    sdk, manager = client
    manager.oem = Manager.model_validate({"Oem": {"Public": {
        "SecurityService": {"@odata.id": "/custom/security"},
    }}}).oem
    calls = serve(monkeypatch, sdk, {
        "/custom/security": {"Links": {"HttpsCert": {"@odata.id": CERT}},
                             "HttpsCert": {"@odata.id": "/unused/cert"}},
        CERT: {"X509CertificateInformation": {"ServerCert": {"Subject": "legacy", "Issuer": "CA"}}},
    })
    result = sdk.get_https_cert()
    assert result.x509_certificate_information.server_cert.subject == "legacy"
    assert result.x509_certificate_information.server_cert.issuer == "CA"
    assert calls == ["/custom/security", CERT]


@pytest.mark.parametrize("value", [None, "legacy", {"CommonName": "example.test"}])
@pytest.mark.parametrize("bits", ["2048", 2048])
def test_certificate_identity_variants(value, bits):
    cert = HttpsCert.model_validate({"X509CertificateInformation": {"ServerCert": {
        "Subject": value, "Issuer": value, "PublicKeyLengthBits": bits,
    }}}).x509_certificate_information.server_cert
    assert cert.public_key_length_bits == 2048
    if isinstance(value, dict):
        assert cert.subject.common_name == value["CommonName"]
    else:
        assert cert.subject == value
    assert HttpsCert.model_validate({}).x509_certificate_information is None


def test_inline_firewall_rules_follow_security_link(client, monkeypatch):
    sdk, _ = client
    calls = serve(monkeypatch, sdk, {
        SECURITY: {"FirewallRules": {"@odata.id": FIREWALL}},
        FIREWALL: {"ActiveStrategy": "Drop", "Rules": [{
            "RuleType": "Drop", "@odata.id": f"{FIREWALL}#/Rules/Example",
            "StartDateTime": "2026-10-22", "EndDateTime": "2026-10-24",
            "StartIPAddress": "192.0.2.1", "EndIPAddress": "192.0.2.5",
            "StartMacAddress": None, "EndMacAddress": None, "WorkdayOnly": False,
        }]},
    })
    result = sdk.get_firewall_rules()
    assert result.active_strategy == "Drop"
    rule = result.rules[0]
    assert rule.rule_type == "Drop" and rule.workday_only is False
    assert rule.start_mac_address is None and rule.end_mac_address is None
    assert rule.start_date_time == "2026-10-22" and rule.end_date_time == "2026-10-24"
    assert rule.start_ip_address == "192.0.2.1" and rule.end_ip_address == "192.0.2.5"
    assert rule.odata_id == f"{FIREWALL}#/Rules/Example"
    assert result.members is None
    assert calls == [SECURITY, FIREWALL]


def test_manager_firewall_link_preserves_collection(client, monkeypatch):
    sdk, manager = client
    manager.oem = Manager.model_validate({"Oem": {"Public": {
        "FirewallRules": {"@odata.id": FIREWALL},
    }}}).oem
    calls = serve(monkeypatch, sdk, {FIREWALL: {"Members@odata.count": 1,
        "Members": [{"@odata.id": "/vendor/rule"}]}})
    result = sdk.get_firewall_rules()
    assert result.members_count == 1 and result.members[0].odata_id == "/vendor/rule"
    assert calls == [FIREWALL]
    assert FirewallRules.model_validate({"Rules": []}).rules == []


@pytest.mark.parametrize("method", ["get_https_cert", "get_firewall_rules"])
def test_missing_child_does_not_probe_invented_uri(client, monkeypatch, method, caplog):
    sdk, _ = client
    calls = serve(monkeypatch, sdk, {SECURITY: {"@odata.id": SECURITY}})
    with pytest.raises(RedfishNotFoundError):
        getattr(sdk, method)()
    assert calls == [SECURITY]
    assert "not advertised" in caplog.text


@pytest.mark.parametrize("status", [401, 403, 404, 500, 0])
def test_security_failure_propagates_without_probing(client, monkeypatch, status):
    sdk, _ = client
    error = RedfishException(status, "Original downstream message")
    calls = serve(monkeypatch, sdk, {SECURITY: error})
    with pytest.raises(RedfishException) as caught:
        sdk.get_https_cert()
    assert caught.value is error
    assert calls == [SECURITY]


def test_standard_certificate_api_does_not_probe_oem(client, monkeypatch):
    sdk, _ = client
    from redfish_sdk.models.managers import NetworkProtocol
    protocol = NetworkProtocol.model_validate({"HTTPS": {"Certificates": {"@odata.id": CERT}}})
    monkeypatch.setattr(sdk._managers, "network_protocol", lambda manager_id=None: protocol)
    calls = serve(monkeypatch, sdk, {CERT: {"Members": []}})
    assert sdk.get_https_certificates().members == []
    assert calls == [CERT]


def test_malformed_security_response_does_not_fallback(client, monkeypatch):
    sdk, _ = client
    calls = serve(monkeypatch, sdk, {SECURITY: {"HttpsCert": 123}})
    with pytest.raises(ValueError):
        sdk.get_https_cert()
    assert calls == [SECURITY]


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_http_downstream_message_is_preserved(client, status):
    sdk, _ = client
    response = requests.Response()
    response.status_code = status
    response._content = b'{"error":{"code":"Example.Error","message":"  Original downstream message.  "}}'
    response.request = requests.Request("GET", "https://example.test/security").prepare()
    with pytest.raises(RedfishException) as caught:
        sdk._http_client._raise_for_status(response, SECURITY)
    assert caught.value.message == "  Original downstream message.  "
    assert caught.value.status_code == status


@pytest.mark.parametrize("body", [b"", b"invalid", b'{"error":{"message":"  "}}'])
def test_http_missing_message_keeps_legacy_fallback(client, body):
    sdk, _ = client
    response = requests.Response()
    response.status_code = 404
    response._content = body
    response.request = requests.Request("GET", "https://example.test/security").prepare()
    with pytest.raises(RedfishNotFoundError) as caught:
        sdk._http_client._raise_for_status(response, SECURITY)
    assert caught.value.message == f"Resource not found: {SECURITY}"
