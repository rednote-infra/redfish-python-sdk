"""
Offline mode: JSON file data-quality validation tests.

Use JSON files collected by tools/redfish_drill.py, deserialize them into
Pydantic models, and apply the same validation rules as online mode.

Usage:
    # Single directory
    export REDFISH_JSON_DIR="./testdata"
    pytest tests/test_offline_json.py -v

    # Multiple servers in a batch
    export REDFISH_JSON_DIR="./testdata_all"
    pytest tests/test_offline_json.py -v

The json_loader fixture is parameterized dynamically by pytest_generate_tests
in conftest.py. Each JSON data directory produces a separate set of test cases.
"""
from __future__ import annotations

import pytest

from redfish_sdk.models.check import validate_model
from redfish_sdk.models.drive import Drive
from redfish_sdk.models.gpu import Gpu
from redfish_sdk.models.memory import Memory
from redfish_sdk.models.network_adapter import NetworkAdapter
from redfish_sdk.models.pcie_device import PCIeDevice
from redfish_sdk.models.power import Power
from redfish_sdk.models.processor import Processor
from redfish_sdk.models.storage import Storage
from redfish_sdk.models.systems import System
from redfish_sdk.models.thermal import Thermal

try:
    from tests.helpers.field_validator import validate_json_key_present_but_empty
    from tests.helpers.json_loader import RedfishJsonLoader
except ImportError:
    from helpers.field_validator import validate_json_key_present_but_empty
    from helpers.json_loader import RedfishJsonLoader


# ---------------------------------------------------------------------------
# Helper: discover System/Chassis odata.id values automatically
# ---------------------------------------------------------------------------

def _get_system_odata_id(loader: RedfishJsonLoader) -> str:
    """Discover the System @odata.id or skip when it cannot be found."""
    oid = loader.find_system_id()
    if oid is None:
        pytest.skip("No JSON file was found for the System resource")
    return oid


def _get_chassis_odata_id(loader: RedfishJsonLoader) -> str:
    """Discover the Chassis @odata.id or skip when it cannot be found."""
    oid = loader.find_chassis_id()
    if oid is None:
        pytest.skip("No JSON file was found for the Chassis resource")
    return oid


# ---------------------------------------------------------------------------
# TC-SYSTEM: system information tests
# ---------------------------------------------------------------------------

class TestOfflineSystem:
    """TC-SYSTEM: Test system information in offline mode."""

    def test_system_info(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)
        system = json_loader.load(system_oid, System)
        if system is None:
            pytest.skip(f"System JSON file does not exist: {system_oid}")

        # Check for keys that are present but empty in the raw JSON.
        raw = json_loader.get_raw(system_oid)
        if raw:
            validate_json_key_present_but_empty(raw, "System", system_oid)

        validate_model(system)


# ---------------------------------------------------------------------------
# TC-PROC: processor information tests
# ---------------------------------------------------------------------------

class TestOfflineProcessors:
    """TC-PROC: Test processor information in offline mode."""

    def test_processors(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)

        # Try multiple possible collection paths.
        proc_collection_oid = f"{system_oid}/Processors"
        processors = json_loader.load_collection_members(proc_collection_oid, Processor)

        if not processors:
            pytest.skip(f"Processors JSON file is missing or empty: {proc_collection_oid}")

        for cpu in processors:
            # Validate the raw JSON.
            raw = json_loader.get_raw(cpu.odata_id) if cpu.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "Processor", cpu.odata_id)

            validate_model(cpu)


# ---------------------------------------------------------------------------
# TC-MEM: memory information tests
# ---------------------------------------------------------------------------

class TestOfflineMemory:
    """TC-MEM: Test memory information in offline mode."""

    def test_memory(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)

        mem_collection_oid = f"{system_oid}/Memory"
        memories = json_loader.load_collection_members(mem_collection_oid, Memory)

        if not memories:
            pytest.skip(f"Memory JSON file is missing or empty: {mem_collection_oid}")

        for mem in memories:
            raw = json_loader.get_raw(mem.odata_id) if mem.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "Memory", mem.odata_id)

            validate_model(mem)


# ---------------------------------------------------------------------------
# TC-STORAGE: storage-controller information tests
# ---------------------------------------------------------------------------

class TestOfflineStorage:
    """TC-STORAGE: Test storage-controller information in offline mode."""

    def test_storages(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)

        storage_collection_oid = f"{system_oid}/Storage"
        storages = json_loader.load_collection_members(storage_collection_oid, Storage)

        if not storages:
            pytest.skip(f"Storage JSON file is missing or empty: {storage_collection_oid}")

        for storage in storages:
            raw = json_loader.get_raw(storage.odata_id) if storage.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "Storage", storage.odata_id)

            validate_model(storage)


# ---------------------------------------------------------------------------
# TC-GPU: GPU information tests
# ---------------------------------------------------------------------------

class TestOfflineGpu:
    """TC-GPU: Test GPU information in offline mode."""

    def test_gpus(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)

        # Strategy 1: GraphicsControllers.
        gc_oid = f"{system_oid}/GraphicsControllers"
        gpus = json_loader.load_collection_members(gc_oid, Gpu)

        # Strategy 2: entries in PCIeDevices whose names contain GPU.
        if not gpus:
            chassis_oid = _get_chassis_odata_id(json_loader)
            pcie_oid = f"{chassis_oid}/PCIeDevices"
            all_pcie = json_loader.load_collection_members(pcie_oid, PCIeDevice)
            # Filter PCIe devices whose names contain "GPU".
            gpu_pcie = [d for d in all_pcie if d.name and "GPU" in d.name]
            if gpu_pcie:
                for device in gpu_pcie:
                    gpu = Gpu.model_construct(
                        odata_id=device.odata_id,
                        name=device.name,
                        manufacturer=device.manufacturer,
                        model=device.model,
                    )
                    gpus.append(gpu)

        if not gpus:
            pytest.skip("No GPU resource was found in GraphicsControllers or PCIeDevices")

        for gpu in gpus:
            validate_model(gpu)


# ---------------------------------------------------------------------------
# TC-DRIVE: physical-drive information tests
# ---------------------------------------------------------------------------

class TestOfflineDrives:
    """TC-DRIVE: Test physical-drive information in offline mode."""

    def test_drives(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        drives_collection_oid = f"{chassis_oid}/Drives"
        drives = json_loader.load_collection_members(drives_collection_oid, Drive)

        if not drives:
            # Some vendors do not expose drives under Chassis/1/Drives.
            # Try to discover them through the Storage Drives links.
            system_oid = json_loader.find_system_id()
            if system_oid:
                storage_oid = f"{system_oid}/Storage"
                storages = json_loader.load_collection_members(storage_oid, Storage)
                for s in storages:
                    if s.drives:
                        for link in s.drives:
                            if link.odata_id:
                                d = json_loader.load(link.odata_id, Drive)
                                if d is not None:
                                    drives.append(d)

        if not drives:
            pytest.skip("Drive JSON file is missing or empty")

        for drive in drives:
            raw = json_loader.get_raw(drive.odata_id) if drive.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "Drive", drive.odata_id)

            validate_model(drive)


# ---------------------------------------------------------------------------
# TC-NIC: network-adapter information tests
# ---------------------------------------------------------------------------

class TestOfflineNetworkAdapters:
    """TC-NIC: Test network-adapter information in offline mode."""

    def test_network_adapters(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        nic_collection_oid = f"{chassis_oid}/NetworkAdapters"
        nics = json_loader.load_collection_members(nic_collection_oid, NetworkAdapter)

        if not nics:
            pytest.skip(
                f"NetworkAdapters JSON file is missing or empty: {nic_collection_oid}"
            )

        for nic in nics:
            raw = json_loader.get_raw(nic.odata_id) if nic.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "NetworkAdapter", nic.odata_id)

            validate_model(nic)


# ---------------------------------------------------------------------------
# TC-PCIE: PCIe device information tests
# ---------------------------------------------------------------------------

class TestOfflinePCIeDevices:
    """TC-PCIE: Test PCIe device information in offline mode."""

    def test_pcie_devices(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        pcie_collection_oid = f"{chassis_oid}/PCIeDevices"
        devices = json_loader.load_collection_members(pcie_collection_oid, PCIeDevice)

        if not devices:
            pytest.skip(f"PCIeDevices JSON file is missing or empty: {pcie_collection_oid}")

        for device in devices:
            raw = json_loader.get_raw(device.odata_id) if device.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "PCIeDevice", device.odata_id)

            validate_model(device)


# ---------------------------------------------------------------------------
# TC-POWER: power information tests
# ---------------------------------------------------------------------------

class TestOfflinePower:
    """TC-POWER: Test power information in offline mode."""

    def test_power(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        power_oid = f"{chassis_oid}/Power"
        power = json_loader.load(power_oid, Power)

        if power is None:
            pytest.skip(f"Power JSON file does not exist: {power_oid}")

        # Validate the raw JSON.
        raw = json_loader.get_raw(power_oid)
        if raw:
            validate_json_key_present_but_empty(raw, "Power", power_oid)

        psu_list = power.power_supplies or []
        if not psu_list:
            pytest.skip("power_supplies is empty")

        for psu in psu_list:
            validate_model(psu)


# ---------------------------------------------------------------------------
# TC-THERMAL: thermal information tests
# ---------------------------------------------------------------------------

class TestOfflineThermal:
    """TC-THERMAL: Test thermal information in offline mode."""

    def test_thermal_fans(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        thermal_oid = f"{chassis_oid}/Thermal"
        thermal = json_loader.load(thermal_oid, Thermal)

        if thermal is None:
            pytest.skip(f"Thermal JSON file does not exist: {thermal_oid}")

        fans = thermal.fans or []
        for fan in fans:
            validate_model(fan)

    def test_thermal_temperatures(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        thermal_oid = f"{chassis_oid}/Thermal"
        thermal = json_loader.load(thermal_oid, Thermal)

        if thermal is None:
            pytest.skip(f"Thermal JSON file does not exist: {thermal_oid}")

        temps = thermal.temperatures or []
        for temp in temps:
            validate_model(temp)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
