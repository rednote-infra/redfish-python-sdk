"""Bounded, unauthenticated Redfish SSDP discovery using the standard library."""
from __future__ import annotations

import http.client
import ipaddress
import math
import socket
import time
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from typing import Optional, Union
from urllib.parse import urlunsplit
from uuid import UUID

from ._service_root import normalize_service_root, validated_service_location
from .exceptions import RedfishDiscoveryError, RedfishValidationError

_SERVICE_TARGET = "urn:dmtf-org:service:redfish-rest:1"
_IPV4_MULTICAST = "239.255.255.250"
_IPV6_MULTICAST = "ff02::c"
_SSDP_PORT = 1900
_MULTICAST_HOPS = 2
_MAX_RESPONSE_BYTES = 8192
_MAX_MX = 5
_HTTP_VERSIONS = frozenset({b"HTTP/1.0", b"HTTP/1.1"})


class DiscoveryProtocol(str, Enum):
    """IP family used for an SSDP M-SEARCH exchange."""

    IPV4 = "ipv4"
    IPV6 = "ipv6"


@dataclass(frozen=True)
class DiscoveredService:
    """Untrusted advertised endpoint metadata, never an authenticated client.

    Validate the expected origin and TLS identity before supplying credentials.
    ``host`` includes brackets/port for IPv6 and can be used as a client host.
    HTTP locations are metadata only; applications should require HTTPS before
    authenticating, for example with allow_insecure_http_auth=False.
    ``location`` is Redfish AL, not the UPnP XML descriptor in LOCATION.
    """

    uuid: str
    location: str
    source_address: str

    def __post_init__(self):
        validated_service_location(self.location)
        try:
            UUID(self.uuid)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RedfishValidationError("Discovered service UUID must be a UUID string") from exc

    @property
    def host(self) -> str:
        """Return the validated authority, including IPv6 brackets and port."""
        return validated_service_location(self.location).netloc

    @property
    def scheme(self) -> str:
        """Return the advertised HTTP(S) scheme; discovery does not authenticate."""
        return validated_service_location(self.location).scheme

    @property
    def service_root(self) -> str:
        """Return the normalized advertised service-root path."""
        return normalize_service_root(validated_service_location(self.location).path or "/")

    @property
    def origin(self) -> str:
        """Return the origin for an application to compare against its allowlist."""
        parts = validated_service_location(self.location)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _redfish_target(value: str) -> bool:
    target = value.casefold()
    return target == _SERVICE_TARGET or (
        target.startswith(_SERVICE_TARGET + ":") and target[len(_SERVICE_TARGET) + 1:].isdigit()
    )


def _parse_reply(data: bytes, source_address: str) -> Optional[DiscoveredService]:
    """Read the SSDP response contract; discard malformed or unrelated packets."""
    if len(data) >= _MAX_RESPONSE_BYTES:
        return None
    status, separator, header_bytes = data.partition(b"\r\n")
    parts = status.split(maxsplit=2)
    if not separator or len(parts) < 2 or parts[0] not in _HTTP_VERSIONS or parts[1] != b"200":
        return None
    try:
        headers = http.client.parse_headers(BytesIO(header_bytes))
        if any(len(headers.get_all(name, [])) != 1 for name in ("ST", "USN", "AL")):
            return None
        target, usn, location = (headers[name].strip() for name in ("ST", "USN", "AL"))
        identifier, delimiter, service = usn.partition("::")
        if not _redfish_target(target) or not delimiter or not _redfish_target(service):
            return None
        if not identifier.casefold().startswith("uuid:"):
            return None
        identity = str(UUID(identifier[len("uuid:"):]))
        if location.startswith("<") and location.endswith(">"):
            location = location[1:-1]
        return DiscoveredService(identity, location, source_address)
    except (http.client.HTTPException, UnicodeError, ValueError, RedfishValidationError):
        return None


def discover_ssdp(timeout: float = 3.0, *, protocol: Union[DiscoveryProtocol, str] = DiscoveryProtocol.IPV4,
                  interface: Optional[Union[str, int]] = None, max_results: int = 256) -> list[DiscoveredService]:
    """Discover endpoints with a finite overall deadline and no HTTP requests.

    ``interface`` is a local IPv4 address for IPv4, or a required interface name
    or positive index for IPv6 link-local multicast. The default IPv4 interface
    is selected by the OS routing table. IPv4 address selection is portable and
    does not require privileged SO_BINDTODEVICE calls. No global socket defaults
    are changed. Duplicate UUID/location pairs are returned once, in arrival order.

    Replies require the Redfish ST/USN and AL service-root URL. LOCATION alone is
    not used because it can identify a UPnP XML descriptor. Schemes, authorities,
    paths and UUIDs are validated, but announcements do not establish identity.
    No credentials are accepted, and no discovered endpoint is fetched. Callers
    must approve an expected origin and configure TLS trust before authentication.
    All IPv4/IPv6 sockets are closed on success, timeout and failure.
    """
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise RedfishValidationError("Discovery timeout must be finite and positive")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
        raise RedfishValidationError("max_results must be a positive integer")
    try:
        protocol = DiscoveryProtocol(protocol)
    except (TypeError, ValueError) as exc:
        raise RedfishValidationError("Unsupported discovery IP protocol") from exc

    interface_index = 0
    ipv4_address = None
    if protocol is DiscoveryProtocol.IPV4 and interface is not None:
        try:
            if not isinstance(interface, str):
                raise ValueError("Expected IPv4 address")
            ipv4_address = str(ipaddress.IPv4Address(interface))
        except ValueError as exc:
            raise RedfishValidationError("IPv4 interface must be a local IPv4 address") from exc
    elif protocol is DiscoveryProtocol.IPV6:
        try:
            interface_index = socket.if_nametoindex(interface) if isinstance(interface, str) else interface
            if isinstance(interface_index, bool) or not isinstance(interface_index, int) or interface_index < 1:
                raise ValueError("IPv6 multicast requires an interface")
        except (OSError, ValueError) as exc:
            raise RedfishValidationError("IPv6 interface must be a valid name or positive interface index") from exc

    ipv6 = protocol is DiscoveryProtocol.IPV6
    family = socket.AF_INET6 if ipv6 else socket.AF_INET
    group = _IPV6_MULTICAST if ipv6 else _IPV4_MULTICAST
    destination = (group, _SSDP_PORT, 0, interface_index) if ipv6 else (group, _SSDP_PORT)
    authority = f"[{group}]:{_SSDP_PORT}" if ipv6 else f"{group}:{_SSDP_PORT}"
    mx = min(_MAX_MX, max(1, math.ceil(timeout)))
    request = (f"M-SEARCH * HTTP/1.1\r\nHOST: {authority}\r\nMAN: \"ssdp:discover\"\r\n"
               f"ST: {_SERVICE_TARGET}\r\nMX: {mx}\r\n\r\n").encode("ascii")
    deadline = time.monotonic() + timeout
    found: dict[tuple[str, str], DiscoveredService] = {}
    try:
        with socket.socket(family, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.settimeout(timeout)
            if ipv6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, interface_index)
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, _MULTICAST_HOPS)
                sock.bind(("::", 0))
            else:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, _MULTICAST_HOPS)
                if ipv4_address:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ipv4_address))
                    sock.bind((ipv4_address, 0))
            sock.sendto(request, destination)
            while len(found) < max_results:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                try:
                    data, sender = sock.recvfrom(_MAX_RESPONSE_BYTES)
                except socket.timeout:
                    break
                service = _parse_reply(data, sender[0])
                if service is not None:
                    found.setdefault((service.uuid, service.location), service)
    except OSError as exc:
        raise RedfishDiscoveryError(0, f"SSDP discovery failed: {exc}") from exc
    return list(found.values())
