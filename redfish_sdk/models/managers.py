"""
Manager (BMC) resource models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link, Status


class CommandShell(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    connect_types_supported: Optional[List[str]] = Field(None, alias="ConnectTypesSupported")
    max_concurrent_sessions: Optional[int] = Field(None, alias="MaxConcurrentSessions")
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")


class GraphicalConsole(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    connect_types_supported: Optional[List[str]] = Field(None, alias="ConnectTypesSupported")
    max_concurrent_sessions: Optional[int] = Field(None, alias="MaxConcurrentSessions")
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")


class SerialConsole(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    connect_types_supported: Optional[List[str]] = Field(None, alias="ConnectTypesSupported")
    max_concurrent_sessions: Optional[int] = Field(None, alias="MaxConcurrentSessions")
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")


class Manager(Entity):
    """
    Represents a BMC (Baseboard Management Controller) manager.
    Endpoint: /redfish/v1/Managers/{managerId}

    """
    date_time: Optional[str] = Field(None, alias="DateTime")
    date_time_local_offset: Optional[str] = Field(None, alias="DateTimeLocalOffset")
    command_shell: Optional[CommandShell] = Field(None, alias="CommandShell")
    graphical_console: Optional[GraphicalConsole] = Field(None, alias="GraphicalConsole")
    serial_console: Optional[SerialConsole] = Field(None, alias="SerialConsole")
    dedicated_network_ports: Optional[Link] = Field(None, alias="DedicatedNetworkPorts")
    ethernet_interfaces: Optional[Link] = Field(None, alias="EthernetInterfaces")
    firmware_version: Optional[str] = Field(None, alias="FirmwareVersion")
    host_interfaces: Optional[Link] = Field(None, alias="HostInterfaces")
    log_services: Optional[Link] = Field(None, alias="LogServices")
    manager_type: Optional[str] = Field(None, alias="ManagerType")
    model: Optional[str] = Field(None, alias="Model")
    network_protocol: Optional[Link] = Field(None, alias="NetworkProtocol")
    power_state: Optional[str] = Field(None, alias="PowerState")
    security_policy: Optional[Link] = Field(None, alias="SecurityPolicy")
    serial_interfaces: Optional[Link] = Field(None, alias="SerialInterfaces")
    service_entry_point_uuid: Optional[str] = Field(None, alias="ServiceEntryPointUUID")
    status: Optional[Status] = Field(None, alias="Status")
    uuid: Optional[str] = Field(None, alias="UUID")


# ---------------------------------------------------------------------------
# NetworkProtocol
# ---------------------------------------------------------------------------

class ProtocolConfig(BaseModel):
    """Generic protocol configuration (SSH, HTTPS, IPMI, etc.)."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    port: Optional[int] = Field(None, alias="Port")
    protocol_enabled: Optional[bool] = Field(None, alias="ProtocolEnabled")


class NetworkProtocol(Entity):
    """
    Network protocol configuration for a manager (BMC).
    Endpoint: /redfish/v1/Managers/{managerId}/NetworkProtocol

    """
    fqdn: Optional[str] = Field(None, alias="FQDN")
    host_name: Optional[str] = Field(None, alias="HostName")
    http: Optional[ProtocolConfig] = Field(None, alias="HTTP")
    https: Optional[ProtocolConfig] = Field(None, alias="HTTPS")
    ipmi: Optional[ProtocolConfig] = Field(None, alias="IPMI")
    ssh: Optional[ProtocolConfig] = Field(None, alias="SSH")
    snmp: Optional[ProtocolConfig] = Field(None, alias="SNMP")
    virtual_media: Optional[ProtocolConfig] = Field(None, alias="VirtualMedia")
    kvmip: Optional[ProtocolConfig] = Field(None, alias="KVMIP")
    status: Optional[Status] = Field(None, alias="Status")


# ---------------------------------------------------------------------------
# EthernetInterface
# ---------------------------------------------------------------------------

class IPv4Address(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    address: Optional[str] = Field(None, alias="Address")
    address_origin: Optional[str] = Field(None, alias="AddressOrigin")
    gateway: Optional[str] = Field(None, alias="Gateway")
    subnet_mask: Optional[str] = Field(None, alias="SubnetMask")


class IPv6Address(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    address: Optional[str] = Field(None, alias="Address")
    address_origin: Optional[str] = Field(None, alias="AddressOrigin")
    address_state: Optional[str] = Field(None, alias="AddressState")
    prefix_length: Optional[int] = Field(None, alias="PrefixLength")


class Vlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    vlan_id: Optional[int] = Field(None, alias="VLANId")
    vlan_enable: Optional[bool] = Field(None, alias="VLANEnable")


class EthernetInterface(Entity):
    """
    Represents a BMC Ethernet interface.
    Endpoint: /redfish/v1/Managers/{managerId}/EthernetInterfaces/{id}

    """
    auto_neg: Optional[bool] = Field(None, alias="AutoNeg")
    fqdn: Optional[str] = Field(None, alias="FQDN")
    full_duplex: Optional[bool] = Field(None, alias="FullDuplex")
    host_name: Optional[str] = Field(None, alias="HostName")
    ipv4_addresses: Optional[List[IPv4Address]] = Field(None, alias="IPv4Addresses")
    ipv6_addresses: Optional[List[IPv6Address]] = Field(None, alias="IPv6Addresses")
    ipv6_default_gateway: Optional[str] = Field(None, alias="IPv6DefaultGateway")
    interface_enabled: Optional[bool] = Field(None, alias="InterfaceEnabled")
    link_status: Optional[str] = Field(None, alias="LinkStatus")
    mac_address: Optional[str] = Field(None, alias="MACAddress")
    mtu_size: Optional[int] = Field(None, alias="MTUSize")
    name_servers: Optional[List[str]] = Field(None, alias="NameServers")
    permanent_mac_address: Optional[str] = Field(None, alias="PermanentMACAddress")
    speed_mbps: Optional[int] = Field(None, alias="SpeedMbps")
    vlan: Optional[Vlan] = Field(None, alias="VLAN")
    status: Optional[Status] = Field(None, alias="Status")


# ---------------------------------------------------------------------------
# HostInterface
# ---------------------------------------------------------------------------

class HostInterface(Entity):
    """
    Represents a host interface for BMC-to-host communication.
    Endpoint: /redfish/v1/Managers/{managerId}/HostInterfaces/{id}
    """
    host_interface_type: Optional[str] = Field(None, alias="HostInterfaceType")
    interface_enabled: Optional[bool] = Field(None, alias="InterfaceEnabled")
    network_protocol: Optional[Link] = Field(None, alias="NetworkProtocol")
    status: Optional[Status] = Field(None, alias="Status")
