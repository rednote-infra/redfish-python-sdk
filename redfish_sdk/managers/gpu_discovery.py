"""Standards-based GPU topology discovery."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from ..exceptions import RedfishException
from ..models.chassis import PCIeDevice
from ..models.gpu import AccelerationFunction, Gpu, GpuOEM, PCIeFunction
from ..models.processor import Processor

if TYPE_CHECKING:
    from ..client import RedfishClient
    from ..models.systems import System

logger = logging.getLogger(__name__)

_GPU_PCIE_FUNCTION_CLASSES = {
    "displaycontroller",
    "processingaccelerators",
    "coprocessor",
}


def _link_ids(links: Optional[List]) -> set[str]:
    return {link.odata_id for link in links or [] if link.odata_id}


class _GpuInventory:
    """Merge resource representations that share standard topology links."""

    def __init__(self) -> None:
        self.candidates: List[tuple[Gpu, set[str]]] = []

    def add(self, gpu: Gpu, source_type: str, identities: set[str]) -> None:
        if gpu.odata_id:
            identities.add(gpu.odata_id)
        serial = gpu.oem and gpu.oem.serial_number
        if serial and serial.strip().casefold() not in {"n/a", "not available"}:
            identities.add(f"serial:{serial.strip().casefold()}")

        gpu.source_types = [source_type]
        gpu.source_odata_ids = [gpu.odata_id] if gpu.odata_id else []
        gpu.related_resource_odata_ids = self._public_ids(identities)
        matches = [item for item in self.candidates if item[1] & identities]
        if not matches:
            self.candidates.append((gpu, identities))
            return

        primary, primary_ids = matches[0]
        self._merge(primary, gpu)
        primary_ids.update(identities)
        for duplicate in matches[1:]:
            other, other_ids = duplicate
            self._merge(primary, other)
            primary_ids.update(other_ids)
            self.candidates.remove(duplicate)
        primary.related_resource_odata_ids = self._public_ids(primary_ids)

    @staticmethod
    def _merge(primary: Gpu, other: Gpu) -> None:
        for field_name in ("name", "manufacturer", "model", "version", "power_watts"):
            if getattr(primary, field_name) is None:
                setattr(primary, field_name, getattr(other, field_name))
        if primary.oem is None and other.oem is not None:
            primary.oem = other.oem
        primary.source_types = list(
            dict.fromkeys(primary.source_types + other.source_types)
        )
        primary.source_odata_ids = list(
            dict.fromkeys(primary.source_odata_ids + other.source_odata_ids)
        )

    @staticmethod
    def _public_ids(identities: set[str]) -> List[str]:
        return sorted(item for item in identities if not item.startswith("serial:"))

    def result(self) -> List[Gpu]:
        return [gpu for gpu, _ in self.candidates]


def discover_gpus(client: RedfishClient, systems: List[System]) -> List[Gpu]:
    """Discover logical GPUs across advertised ComputerSystem resources."""
    inventory = _GpuInventory()
    for system in systems:
        _add_graphics_controllers(client, system, inventory)
        _add_processor_accelerators(client, system, inventory)
        _add_pcie_devices(client, system, inventory)
    return inventory.result()


def _add_graphics_controllers(
    client: RedfishClient, system: System, inventory: _GpuInventory
) -> None:
    if not system.graphics_controllers or not system.graphics_controllers.odata_id:
        return
    try:
        controllers = client._get_collection(
            system.graphics_controllers.odata_id, Gpu
        )
    except RedfishException as exc:
        logger.warning("GraphicsControllers fetch failed: %s", exc)
        return
    for gpu in controllers:
        identities: set[str] = set()
        if gpu.links:
            if gpu.links.pcie_device and gpu.links.pcie_device.odata_id:
                identities.add(gpu.links.pcie_device.odata_id)
            identities.update(_link_ids(gpu.links.pcie_functions))
            identities.update(_link_ids(gpu.links.processors))
        inventory.add(gpu, "GraphicsController", identities)


def _add_processor_accelerators(
    client: RedfishClient, system: System, inventory: _GpuInventory
) -> None:
    if not system.processors or not system.processors.odata_id:
        return
    try:
        processors = client._get_collection(system.processors.odata_id, Processor)
    except RedfishException as exc:
        logger.warning("Processors fetch failed during GPU discovery: %s", exc)
        return
    for processor in processors:
        processor_type = (processor.processor_type or "").casefold()
        accelerator_label = " ".join(
            value for value in (processor.name, processor.model) if value
        ).casefold()
        if processor_type != "gpu" and not (
            processor_type == "accelerator" and "gpu" in accelerator_label
        ):
            continue
        identities: set[str] = set()
        if processor.links:
            if processor.links.pcie_device and processor.links.pcie_device.odata_id:
                identities.add(processor.links.pcie_device.odata_id)
            identities.update(_link_ids(processor.links.pcie_functions))
        gpu = Gpu.model_construct(
            odata_id=processor.odata_id,
            id=processor.id,
            name=processor.name,
            manufacturer=processor.manufacturer,
            model=processor.model,
            version=processor.firmware_version,
            power_watts=str(processor.tdp_watts)
            if processor.tdp_watts is not None
            else None,
            oem=GpuOEM.model_construct(serial_number=processor.serial_number)
            if processor.serial_number
            else None,
        )
        _enrich_from_acceleration_functions(client, processor, gpu, identities)
        inventory.add(gpu, "Processor", identities)


def _enrich_from_acceleration_functions(
    client: RedfishClient,
    processor: Processor,
    gpu: Gpu,
    identities: set[str],
) -> None:
    link = processor.acceleration_functions
    if not link or not link.odata_id:
        return
    try:
        functions = client._get_collection(link.odata_id, AccelerationFunction)
    except RedfishException as exc:
        logger.warning(
            "AccelerationFunctions fetch failed for %s: %s", processor.odata_id, exc
        )
        return
    for function in functions:
        if function.odata_id:
            identities.add(function.odata_id)
        if function.links:
            identities.update(_link_ids(function.links.pcie_functions))
        gpu.manufacturer = gpu.manufacturer or function.manufacturer
        gpu.version = gpu.version or function.version
        if gpu.power_watts is None and function.power_watts is not None:
            gpu.power_watts = str(function.power_watts)


def _add_pcie_devices(
    client: RedfishClient, system: System, inventory: _GpuInventory
) -> None:
    from .chassis import ChassisManager

    devices: dict[str, PCIeDevice] = {}
    try:
        chassis = ChassisManager(client).get()
        if chassis.pcie_devices and chassis.pcie_devices.odata_id:
            for device in client._get_collection(
                chassis.pcie_devices.odata_id, PCIeDevice
            ):
                if device.odata_id:
                    devices[device.odata_id] = device
    except RedfishException as exc:
        logger.warning("Chassis PCIeDevices fetch failed: %s", exc)

    links = list(system.pcie_devices or [])
    if system.links:
        links.extend(system.links.pcie_devices or [])
    for link in sorted(links, key=lambda item: item.odata_id or ""):
        if not link.odata_id or link.odata_id in devices:
            continue
        try:
            device = client._http_client.get(link.odata_id, PCIeDevice)
        except RedfishException as exc:
            logger.warning("PCIeDevice fetch failed for %s: %s", link.odata_id, exc)
            continue
        if device.odata_id:
            devices[device.odata_id] = device

    function_cache: dict[str, PCIeFunction] = {}
    for device in devices.values():
        functions = _device_functions(client, device, function_cache)
        standard_signal = any(
            (function.device_class or "").replace(" ", "").casefold()
            in _GPU_PCIE_FUNCTION_CLASSES
            for function in functions
        )
        legacy_signal = "gpu" in (device.name or "").casefold()
        type_signal = (device.device_type or "").casefold() == "gpu"
        if not (standard_signal or legacy_signal or type_signal):
            continue
        gpu = _gpu_from_pcie_device(device)
        identities = {device.odata_id} if device.odata_id else set()
        identities.update(
            function.odata_id for function in functions if function.odata_id
        )
        if device.links:
            identities.update(_link_ids(device.links.processors))
        inventory.add(gpu, "PCIeDevice", identities)


def _device_functions(
    client: RedfishClient,
    device: PCIeDevice,
    cache: dict[str, PCIeFunction],
) -> List[PCIeFunction]:
    functions: List[PCIeFunction] = []
    if device.pcie_functions and device.pcie_functions.odata_id:
        try:
            functions.extend(
                client._get_collection(device.pcie_functions.odata_id, PCIeFunction)
            )
        except RedfishException as exc:
            logger.warning(
                "PCIeFunctions collection fetch failed for %s: %s",
                device.odata_id,
                exc,
            )
    paths = sorted(_link_ids(device.links and device.links.pcie_functions))
    for path in paths:
        function = cache.get(path)
        if function is None:
            try:
                function = client._http_client.get(path, PCIeFunction)
            except RedfishException as exc:
                logger.warning("PCIeFunction fetch failed for %s: %s", path, exc)
                continue
            cache[path] = function
        if all(existing.odata_id != function.odata_id for existing in functions):
            functions.append(function)
    return functions


def _gpu_from_pcie_device(device: PCIeDevice) -> Gpu:
    gpu = Gpu.model_construct(
        odata_id=device.odata_id,
        id=device.id,
        name=device.name,
        manufacturer=device.manufacturer,
        model=device.model,
        power_watts=None,
        version=device.firmware_version or device.card_model or device.part_number,
    )
    public = device.oem and device.oem.gpu_oem_public
    if public and public.power_watts is not None and public.power_watts > 0:
        gpu.power_watts = str(public.power_watts)
    if device.serial_number:
        gpu.oem = GpuOEM.model_construct(serial_number=device.serial_number)
    return gpu
