"""
Manager (BMC) resource models.

"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link, Status
from .oem import Oem


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
    oem: Optional[Oem] = Field(None, alias="Oem")
    # Redfish Actions block (e.g. #Manager.Reset, #Manager.ResetToDefaults,
    # OEM downloads such as #Manager.GeneralDownload).
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")


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


# ---------------------------------------------------------------------------
# KvmService (OEM extension, dynamically discovered via Manager OEM links)
# ---------------------------------------------------------------------------

class KvmService(Entity):
    """
    KVM service configuration for a manager (BMC).

    This is an OEM extension resource whose URI is dynamically discovered
    from the Manager's ``Oem.{vendor}.KVM`` link.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/KvmService``

    """
    kvm_url: Optional[str] = Field(None, alias="KvmUrl")
    maximum_number_of_sessions: Optional[int] = Field(
        None, alias="MaximumNumberOfSessions",
    )
    number_of_activated_sessions: Optional[int] = Field(
        None, alias="NumberOfActivatedSessions",
    )
    session_timeout_minutes: Optional[int] = Field(
        None, alias="SessionTimeoutMinutes",
    )
    encryption_enabled: Optional[bool] = Field(None, alias="EncryptionEnabled")
    activated_sessions_type: Optional[str] = Field(
        None, alias="ActivatedSessionsType",
    )


# ---------------------------------------------------------------------------
# NtpService (OEM extension)
# ---------------------------------------------------------------------------

class NtpService(Entity):
    """
    NTP service configuration for a manager (BMC).

    OEM extension resource dynamically discovered from
    ``Oem.{vendor}.NtpService``.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/NtpService``

    """
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    ntp_server_type: Optional[str] = Field(None, alias="NtpServerType")
    primary_ntp_server: Optional[str] = Field(None, alias="PrimaryNtpServer")
    secondary_ntp_server: Optional[str] = Field(None, alias="SecondaryNtpServer")
    third_ntp_server: Optional[str] = Field(None, alias="ThirdNtpServer")
    fourth_ntp_server: Optional[str] = Field(None, alias="FourthNtpServer")
    fifth_ntp_server: Optional[str] = Field(None, alias="FifthNtpServer")
    sixth_ntp_server: Optional[str] = Field(None, alias="SixthNtpServer")
    polling_interval: Optional[int] = Field(None, alias="PollingInterval")
    max_variety: Optional[int] = Field(None, alias="MaxVariety")


# ---------------------------------------------------------------------------
# SyslogService (OEM extension)
# ---------------------------------------------------------------------------

class SyslogServer(BaseModel):
    """Individual syslog server configuration entry."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    member_id: Optional[int] = Field(None, alias="MemberId")
    enabled: Optional[str] = Field(None, alias="Enabled")
    logtype: Optional[str] = Field(None, alias="Logtype")
    address: Optional[str] = Field(None, alias="Address")
    port: Optional[int] = Field(None, alias="Port")


class SyslogService(Entity):
    """
    Syslog service configuration for a manager (BMC).

    OEM extension resource dynamically discovered from
    ``Oem.{vendor}.SyslogService``.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/SyslogService``

    """
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    service_syslog_tag: Optional[str] = Field(None, alias="ServiceSyslogTag")
    service_syslog_enable: Optional[str] = Field(None, alias="ServiceSyslogEnable")
    alarm_severity: Optional[str] = Field(None, alias="AlarmSeverity")
    transmission_protocol: Optional[str] = Field(None, alias="TransmissionProtocol")
    syslog_servers: Optional[List[SyslogServer]] = Field(None, alias="SyslogServers")


# ---------------------------------------------------------------------------
# SnmpService (OEM extension)
# ---------------------------------------------------------------------------

class TrapServer(BaseModel):
    """Individual SNMP trap server entry."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    id: Optional[int] = Field(None, alias="Id")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    destination: Optional[str] = Field(None, alias="Destination")
    port: Optional[int] = Field(None, alias="Port")


class SnmpTrapNotification(BaseModel):
    """SNMP trap notification configuration."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    trap_version: Optional[str] = Field(None, alias="TrapVersion")
    event_level_limit: Optional[str] = Field(None, alias="EventLevelLimit")
    community: Optional[str] = Field(None, alias="Community")
    host_id: Optional[str] = Field(None, alias="HostID")
    user_name: Optional[str] = Field(None, alias="UserName")
    auth_protocol: Optional[str] = Field(None, alias="AuthProtocol")
    auth_password: Optional[str] = Field(None, alias="AuthPassword")
    priv_protocol: Optional[str] = Field(None, alias="PrivProtocol")
    priv_password: Optional[str] = Field(None, alias="PrivPassword")
    engine_id: Optional[str] = Field(None, alias="EngineID")
    device_type: Optional[int] = Field(None, alias="DeviceType")
    trap_server: Optional[List[TrapServer]] = Field(None, alias="TrapServer")


class SnmpService(Entity):
    """
    SNMP service configuration for a manager (BMC).

    OEM extension resource dynamically discovered from
    ``Oem.{vendor}.SnmpService``.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/SnmpService``

    """
    snmp_v1_enable: Optional[bool] = Field(None, alias="SnmpV1Enable")
    snmp_v2c_enable: Optional[bool] = Field(None, alias="SnmpV2CEnable")
    snmp_v3_enable: Optional[bool] = Field(None, alias="SnmpV3Enable")
    read_only_community: Optional[str] = Field(None, alias="ReadOnlyCommunity")
    read_write_community: Optional[str] = Field(None, alias="ReadWriteCommunity")
    snmp_v3_auth_protocol: Optional[str] = Field(None, alias="SnmpV3AuthProtocol")
    snmp_v3_auth_password: Optional[str] = Field(None, alias="SnmpV3AuthPassword")
    snmp_v3_priv_protocol: Optional[str] = Field(None, alias="SnmpV3PrivProtocol")
    snmp_v3_priv_password: Optional[str] = Field(None, alias="SnmpV3PrivPassword")
    snmp_v3_auth_user_name: Optional[str] = Field(None, alias="SnmpV3AuthUserName")
    snmp_trap_notification: Optional[SnmpTrapNotification] = Field(
        None, alias="SnmpTrapNotification",
    )


# ---------------------------------------------------------------------------
# LldpService (OEM extension)
# ---------------------------------------------------------------------------

class LldpService(Entity):
    """
    LLDP service configuration for a manager (BMC).

    OEM extension resource dynamically discovered from
    ``Oem.{vendor}.LldpService``.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/LldpService``

    """
    lldp_enabled: Optional[bool] = Field(None, alias="LldpEnabled")
    work_mode: Optional[str] = Field(None, alias="WorkMode")


# ---------------------------------------------------------------------------
# DnsService (OEM extension — not all BMC vendors support this)
# ---------------------------------------------------------------------------

class DnsService(Entity):
    """
    DNS service configuration for a manager (BMC).

    OEM extension resource. Not all BMC vendors support this endpoint.
    Typical endpoint: ``/redfish/v1/Managers/{managerId}/DnsService``

    """
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    host_name: Optional[str] = Field(None, alias="HostName")
    domain_name: Optional[str] = Field(None, alias="DomainName")
    dns_servers: Optional[List[str]] = Field(None, alias="DnsServers")


# ---------------------------------------------------------------------------
# VncService (OEM extension)
# ---------------------------------------------------------------------------

class VncService(Entity):
    """
    VNC/RFB service configuration for a manager (BMC).

    OEM extension resource dynamically discovered from
    ``Oem.{vendor}.RfbService``.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/VncService``

    Note: The OEM key is ``RfbService`` but the resource URI is ``VncService``.

    """
    rfb_non_secure: Optional[bool] = Field(None, alias="RfbNonSecure")
    rfb_over_ssh: Optional[bool] = Field(None, alias="RfbOverSsh")
    rfb_over_stunnel: Optional[bool] = Field(None, alias="RfbOverStunnel")
    protocol_enabled: Optional[bool] = Field(None, alias="ProtocolEnabled")
    max_allow_session: Optional[int] = Field(None, alias="MaxAllowSession")
    non_secure_access_port: Optional[int] = Field(None, alias="NonSecureAccessPort")
    secure_access_port: Optional[int] = Field(None, alias="SecureAccessPort")
    timeout: Optional[int] = Field(None, alias="Timeout")
    current_active_session: Optional[int] = Field(None, alias="CurrentActiveSession")


# ---------------------------------------------------------------------------
# SecurityService + HttpsCert (OEM extension)
# ---------------------------------------------------------------------------

class SecurityServiceLinks(BaseModel):
    """Links within SecurityService resource."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    https_cert: Optional[Link] = Field(None, alias="HttpsCert")


class SecurityService(Entity):
    """
    Security service for a manager (BMC).

    OEM extension resource dynamically discovered from
    ``Oem.{vendor}.SecurityService``.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/SecurityService``

    """
    links: Optional[SecurityServiceLinks] = Field(None, alias="Links")


class ServerCert(BaseModel):
    """X.509 server certificate details."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    subject: Optional[str] = Field(None, alias="Subject")
    issuer: Optional[str] = Field(None, alias="Issuer")
    valid_not_before: Optional[str] = Field(None, alias="ValidNotBefore")
    valid_not_after: Optional[str] = Field(None, alias="ValidNotAfter")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    signature_algorithm: Optional[str] = Field(None, alias="SignatureAlgorithm")
    key_usage: Optional[str] = Field(None, alias="KeyUsage")
    public_key_length_bits: Optional[int] = Field(None, alias="PublicKeyLengthBits")


class X509CertificateInformation(BaseModel):
    """X.509 certificate information wrapper."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    server_cert: Optional[ServerCert] = Field(None, alias="ServerCert")


class HttpsCert(Entity):
    """
    HTTPS certificate information for a manager (BMC).

    Discovered via ``SecurityService.Links.HttpsCert``.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/SecurityService/HttpsCert``

    """
    x509_certificate_information: Optional[X509CertificateInformation] = Field(
        None, alias="X509CertificateInformation",
    )


# ---------------------------------------------------------------------------
# FirewallRules (OEM extension — Collection resource)
# ---------------------------------------------------------------------------

class FirewallRules(Entity):
    """
    Firewall rules collection for a manager (BMC).

    OEM extension resource dynamically discovered from
    ``Oem.{vendor}.FirewallRules``.  Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/FirewallRules``

    This is a Collection resource; members can be accessed individually
    via their ``@odata.id``.

    """
    members_count: Optional[int] = Field(None, alias="Members@odata.count")
    members: Optional[List[Link]] = Field(None, alias="Members")


# ---------------------------------------------------------------------------
# VirtualMedia (standard Redfish resource)
# ---------------------------------------------------------------------------

class VirtualMedia(Entity):
    """
    Virtual media resource for a manager (BMC).

    Standard Redfish resource. Typical endpoint:
    ``/redfish/v1/Managers/{managerId}/VirtualMedia/{mediaId}``

    """
    media_types: Optional[List[str]] = Field(None, alias="MediaTypes")
    image: Optional[str] = Field(None, alias="Image")
    image_name: Optional[str] = Field(None, alias="ImageName")
    connected_via: Optional[str] = Field(None, alias="ConnectedVia")
    inserted: Optional[bool] = Field(None, alias="Inserted")
    transfer_protocol_type: Optional[str] = Field(None, alias="TransferProtocolType")
    verify_certificate: Optional[bool] = Field(None, alias="VerifyCertificate")


# ---------------------------------------------------------------------------
# SOLSourceControlInfo (OEM extension — not all BMC vendors support this)
# ---------------------------------------------------------------------------

class SolSourceControlInfo(Entity):
    """
    SOL (Serial Over LAN) source control information for a manager (BMC).

    OEM extension resource. Not all BMC vendors support this endpoint.
    Typical endpoint: ``/redfish/v1/Managers/{managerId}/SOLSourceControlInfo``

    """
    pass
