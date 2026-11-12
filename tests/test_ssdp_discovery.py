"""Discovery uses bounded mocked UDP only and never authenticates or fetches URLs."""
import socket
from unittest.mock import Mock

import pytest

import redfish_sdk as sdk

SERVICE = "urn:dmtf-org:service:redfish-rest:1"
UUID = "92384634-2938-2342-8820-489239905423"


def packet(location="https://192.0.2.10/redfish/v1/", *, target=SERVICE, extra=""):
    return (f"HTTP/1.1 200 OK\r\nST: {target}\r\nUSN: uuid:{UUID}::{target}\r\n"
            f"AL: {location}\r\n{extra}\r\n").encode()


class DatagramSocket:
    def __init__(self, packets=()):
        self.packets = list(packets)
        self.options = []
        self.timeouts = []
        self.sent = []
        self.bound = None
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def setsockopt(self, *args):
        self.options.append(args)

    def settimeout(self, value):
        self.timeouts.append(value)

    def bind(self, address):
        self.bound = address

    def sendto(self, content, destination):
        self.sent.append((content, destination))

    def recvfrom(self, size):
        if not self.packets:
            raise socket.timeout()
        return self.packets.pop(0), ("192.0.2.10", 1900)


def install_socket(monkeypatch, packets):
    from redfish_sdk import discovery
    fake = DatagramSocket(packets)
    factory = Mock(return_value=fake)
    monkeypatch.setattr(discovery.socket, "socket", factory)
    return fake, factory


def test_discovery_uses_al_instead_of_upnp_location_deduplicates_and_never_fetches(monkeypatch):
    fake, factory = install_socket(monkeypatch, [packet(extra="LOCATION: http://other.example/device.xml\r\n"), packet()])
    http = Mock(side_effect=AssertionError("Discovery must not perform HTTP requests"))
    monkeypatch.setattr("requests.Session.request", http)
    before = socket.getdefaulttimeout()
    services = sdk.discover_ssdp(timeout=0.5)
    assert len(services) == 1
    result = services[0]
    assert result.uuid == UUID
    assert result.location == "https://192.0.2.10/redfish/v1/"
    assert result.host == "192.0.2.10"
    assert result.service_root == "/redfish/v1/"
    assert result.source_address == "192.0.2.10"
    http.assert_not_called()
    assert socket.getdefaulttimeout() == before
    assert fake.closed
    factory.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    assert fake.sent[0][1] == ("239.255.255.250", 1900)
    assert b"Authorization" not in fake.sent[0][0]
    assert b"X-Auth-Token" not in fake.sent[0][0]
    assert SERVICE.encode() in fake.sent[0][0]
    assert all(0 < value <= 0.5 for value in fake.timeouts)


@pytest.mark.parametrize("location", ["file:///etc/passwd", "javascript:alert(1)", "//other.example/root",
    "https://user:password@bmc.example/redfish/v1/", "https://bmc.example:0/root", "https://bmc.example:99999/root",
    "https://bmc.example/root?token=example", "https://bmc.example/root#fragment", "https://bmc.example/a/../root",
    "https://bmc.example\\@other.example/root", "https://bmc.example/path space", "https://[invalid]/root"])
def test_untrusted_malformed_locations_are_ignored(monkeypatch, location):
    fake, _ = install_socket(monkeypatch, [packet(location)])
    assert sdk.discover_ssdp(timeout=0.01) == []
    assert fake.closed


def test_invalid_protocol_messages_and_missing_al_are_ignored(monkeypatch):
    fake, _ = install_socket(monkeypatch, [b"garbage", packet(target="upnp:rootdevice"),
        packet().replace(b"AL:", b"LOCATION:"), packet().replace(UUID.encode(), b"not-a-uuid"),
        packet(extra="AL: https://other.example/\r\n")])
    assert sdk.discover_ssdp(timeout=0.1) == []
    assert fake.closed


def test_ipv4_interface_selection(monkeypatch):
    fake, _ = install_socket(monkeypatch, [])
    sdk.discover_ssdp(interface="192.0.2.20", timeout=0.1)
    assert fake.bound == ("192.0.2.20", 0)
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("192.0.2.20")) in fake.options


def test_ipv6_interface_selection_and_scoped_endpoint(monkeypatch):
    fake, factory = install_socket(monkeypatch, [packet("https://[fe80::1%253]:8443/gateway/redfish/v1/")])
    monkeypatch.setattr(socket, "if_nametoindex", lambda name: 3)
    services = sdk.discover_ssdp(protocol=sdk.DiscoveryProtocol.IPV6, interface="eth-test", timeout=0.1)
    factory.assert_called_once_with(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    assert fake.sent[0][1] == ("ff02::c", 1900, 0, 3)
    assert b"HOST: [ff02::c]:1900" in fake.sent[0][0]
    assert (socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, 3) in fake.options
    assert services[0].host == "[fe80::1%253]:8443"
    assert services[0].service_root == "/gateway/redfish/v1/"


def test_minor_service_versions_are_accepted(monkeypatch):
    install_socket(monkeypatch, [packet(target=SERVICE + ":4")])
    assert len(sdk.discover_ssdp(timeout=0.1)) == 1


def test_timeout_is_an_absolute_deadline_even_with_duplicate_packets(monkeypatch):
    from redfish_sdk import discovery
    fake, _ = install_socket(monkeypatch, [packet()] * 10)
    clock = iter([0.0, 0.1, 0.4, 0.9, 1.1])
    monkeypatch.setattr(discovery.time, "monotonic", lambda: next(clock))
    assert len(sdk.discover_ssdp(timeout=1)) == 1
    assert len(fake.packets) == 7
    assert fake.closed


@pytest.mark.parametrize("options", [{"timeout": 0}, {"timeout": float("inf")}, {"timeout": True},
    {"max_results": 0}, {"max_results": True}, {"protocol": "invalid"}, {"interface": "not-an-ip"},
    {"protocol": "ipv6"}])
def test_invalid_options_fail_before_network_activity(monkeypatch, options):
    _, factory = install_socket(monkeypatch, [])
    with pytest.raises(sdk.RedfishValidationError):
        sdk.discover_ssdp(**options)
    factory.assert_not_called()


def test_network_errors_are_sdk_errors_and_close_socket(monkeypatch):
    fake, _ = install_socket(monkeypatch, [])
    fake.sendto = Mock(side_effect=OSError("Network unavailable"))
    with pytest.raises(sdk.RedfishDiscoveryError):
        sdk.discover_ssdp(timeout=0.1)
    assert fake.closed


def test_result_limit_stops_receiving_without_waiting_for_timeout(monkeypatch):
    fake, _ = install_socket(monkeypatch, [packet(), packet("https://192.0.2.11/root/")])
    assert len(sdk.discover_ssdp(timeout=1, max_results=1)) == 1
    assert len(fake.packets) == 1
    assert fake.closed


def test_receive_failure_preserves_sdk_exception_and_socket_cleanup(monkeypatch):
    fake, _ = install_socket(monkeypatch, [])
    fake.recvfrom = Mock(side_effect=OSError("Receive failed"))
    with pytest.raises(sdk.RedfishDiscoveryError, match="Receive failed"):
        sdk.discover_ssdp(timeout=0.1)
    assert fake.closed
