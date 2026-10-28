"""Read-only discovery of optional CXL and UALink fabric resources."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from ..exceptions import RedfishNotFoundError, RedfishValidationError
from ..models.fabric import CXLLogicalDevice, Port, PortMetrics
from .system_resources import select_member, unique_members

if TYPE_CHECKING:
    from ..client import RedfishClient
    from ..models.pcie_device import PCIeDevice


class FabricManager:
    """Follows service-advertised topology links without deriving paths."""

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def processor_ports(
        self,
        processor_id: Optional[str] = None,
        system_id: Optional[str] = None,
    ) -> List[Port]:
        processors = self._client._systems.processors(system_id)
        if processor_id is not None:
            processors = [select_member(processors, processor_id)]

        result: List[Port] = []
        advertised = False
        for processor in processors:
            if processor.ports and processor.ports.odata_id:
                advertised = True
                result.extend(
                    self._client._get_collection(processor.ports.odata_id, Port)
                )
        if not advertised:
            raise RedfishNotFoundError("Processors do not advertise Ports")
        return unique_members(result)

    def _pcie_device(
        self, pcie_device_id: str, chassis_id: Optional[str]
    ) -> PCIeDevice:
        devices = self._client._chassis.pcie_devices(chassis_id)
        return select_member(devices, pcie_device_id)

    def connected_pcie_ports(
        self, pcie_device_id: str, chassis_id: Optional[str] = None
    ) -> List[Port]:
        device = self._pcie_device(pcie_device_id, chassis_id)
        links = device.links and device.links.connected_pcie_ports
        if not links:
            raise RedfishNotFoundError(
                "PCIeDevice does not advertise Links.ConnectedPCIePorts"
            )
        return unique_members(self._client._get_list(links, Port))

    def _ports(
        self,
        processor_id: Optional[str],
        pcie_device_id: Optional[str],
        system_id: Optional[str],
        chassis_id: Optional[str],
    ) -> List[Port]:
        if processor_id is not None and pcie_device_id is not None:
            raise RedfishValidationError(
                "Specify either processor_id or pcie_device_id, not both"
            )
        if pcie_device_id is not None:
            return self.connected_pcie_ports(pcie_device_id, chassis_id)
        return self.processor_ports(processor_id, system_id)

    def port_metrics(
        self,
        port_id: Optional[str] = None,
        processor_id: Optional[str] = None,
        pcie_device_id: Optional[str] = None,
        system_id: Optional[str] = None,
        chassis_id: Optional[str] = None,
    ) -> PortMetrics:
        ports = self._ports(
            processor_id, pcie_device_id, system_id, chassis_id
        )
        port = select_member(ports, port_id)
        if not port.metrics or not port.metrics.odata_id:
            raise RedfishNotFoundError("Port does not advertise Metrics")
        return self._http.get(port.metrics.odata_id, PortMetrics)

    def cxl_logical_devices(
        self, pcie_device_id: str, chassis_id: Optional[str] = None
    ) -> List[CXLLogicalDevice]:
        device = self._pcie_device(pcie_device_id, chassis_id)
        link = device.cxl_logical_devices
        if not link or not link.odata_id:
            raise RedfishNotFoundError(
                "PCIeDevice does not advertise CXLLogicalDevices"
            )
        return self._client._get_collection(link.odata_id, CXLLogicalDevice)

    def port_cxl_logical_devices(
        self,
        port_id: Optional[str] = None,
        processor_id: Optional[str] = None,
        pcie_device_id: Optional[str] = None,
        system_id: Optional[str] = None,
        chassis_id: Optional[str] = None,
    ) -> List[CXLLogicalDevice]:
        ports = self._ports(
            processor_id, pcie_device_id, system_id, chassis_id
        )
        port = select_member(ports, port_id)
        links = port.links and port.links.cxl_logical_devices
        if not links:
            raise RedfishNotFoundError(
                "Port does not advertise Links.CXLLogicalDevices"
            )
        return unique_members(self._client._get_list(links, CXLLogicalDevice))
