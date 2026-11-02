"""
Redfish resource key enumeration.

Defines all known Redfish resource names as enum members,
enabling IDE auto-completion and preventing typo errors.
"""
from enum import Enum


class RedfishResource(str, Enum):
    """
    Enumeration of Redfish resource identifiers.

    Values correspond to Redfish JSON field names and are grouped by their
    containing resource level.

    Usage::

        from redfish_sdk import RedfishClient, RedfishResource

        client = RedfishClient(host="10.0.0.1", username="admin", password="pwd")
        processors_url = client.get_odata_id(RedfishResource.PROCESSORS)
        # → "/redfish/v1/Systems/1/Processors"
    """

    # RootService level (/redfish/v1/)
    SYSTEMS = "Systems"
    CHASSIS = "Chassis"
    MANAGERS = "Managers"
    ACCOUNT_SERVICE = "AccountService"
    SESSION_SERVICE = "SessionService"
    EVENT_SERVICE = "EventService"
    UPDATE_SERVICE = "UpdateService"
    TASK_SERVICE = "TaskService"
    CERTIFICATE_SERVICE = "CertificateService"
    REGISTRIES = "Registries"
    JSON_SCHEMAS = "JsonSchemas"
    KEY_SERVICE = "KeyService"
    COMPONENT_INTEGRITY = "ComponentIntegrity"

    # System level (/redfish/v1/Systems/{id})
    PROCESSORS = "Processors"
    MEMORY = "Memory"
    STORAGE = "Storage"
    BIOS = "Bios"
    ETHERNET_INTERFACES = "EthernetInterfaces"
    GRAPHICS_CONTROLLERS = "GraphicsControllers"
    LOG_SERVICES = "LogServices"
    NETWORK_INTERFACES = "NetworkInterfaces"
    SECURE_BOOT = "SecureBoot"
    SIMPLE_STORAGE = "SimpleStorage"
    USB_CONTROLLERS = "USBControllers"
    VIRTUAL_MEDIA = "VirtualMedia"
    CERTIFICATES = "Certificates"
    BOOT_OPTIONS = "BootOptions"

    # Chassis level (/redfish/v1/Chassis/{id})
    THERMAL = "Thermal"
    POWER = "Power"
    DRIVES = "Drives"
    NETWORK_ADAPTERS = "NetworkAdapters"
    PCIE_DEVICES = "PCIeDevices"
    SENSORS = "Sensors"

    # Manager level (/redfish/v1/Managers/{id})
    NETWORK_PROTOCOL = "NetworkProtocol"
    HOST_INTERFACES = "HostInterfaces"
    SERIAL_INTERFACES = "SerialInterfaces"
    DEDICATED_NETWORK_PORTS = "DedicatedNetworkPorts"
    SECURITY_POLICY = "SecurityPolicy"
