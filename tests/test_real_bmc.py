"""
Online mode: real-BMC integration tests.

Connect directly to a Redfish-capable BMC via RedfishClient and exercise
read-only resource endpoints to validate response shape and data quality.

Required environment variables (set them before running the test):
    export BMC_IP="<bmc-ip>"
    export BMC_USER="<bmc-user>"
    export BMC_PASSWORD="<bmc-password>"
    pytest tests/test_real_bmc.py -v

All tests are read-only GET operations; no BMC configuration is modified.
"""
from __future__ import annotations

import pytest

from redfish_sdk.models.check import validate_model

# ---------------------------------------------------------------------------
# TC-AUTH: login authentication tests
# ---------------------------------------------------------------------------

class TestAuth:
    """TC-AUTH: Test login authentication."""

    def test_login_and_root_service(self, bmc_client):
        """Verify authentication and retrieval of the root service document."""
        root = bmc_client.root()
        assert root is not None, "root() returned None"
        assert root.odata_id is not None, "RootService.odata_id is None"
        assert root.odata_id.rstrip("/").endswith("redfish/v1"), (
            f"Unexpected RootService.odata_id: {root.odata_id!r}"
        )

    def test_root_has_top_level_links(self, bmc_client):
        """Verify that the root document contains the primary resource links."""
        root = bmc_client.root()
        assert root.systems is not None, "RootService.systems link is missing"
        assert root.chassis is not None, "RootService.chassis link is missing"
        assert root.managers is not None, "RootService.managers link is missing"


# ---------------------------------------------------------------------------
# TC-SYSTEM: system information retrieval tests
# ---------------------------------------------------------------------------

class TestSystem:
    """TC-SYSTEM: Test system information retrieval."""

    def test_system_info(self, bmc_client):
        """Retrieve system information and validate key fields."""
        system = bmc_client.get_system()
        assert system is not None, "systems.get() returned None"
        validate_model(system)


# ---------------------------------------------------------------------------
# TC-PROC: processor (CPU) information tests
# ---------------------------------------------------------------------------

class TestProcessors:
    """TC-PROC: Test processor information."""

    def test_processors(self, bmc_client):
        """Retrieve processors and validate the fields of each CPU."""
        processors = bmc_client.get_processors()
        assert processors is not None, "get_processors() returned None"
        assert len(processors) > 0, "The server must expose at least one CPU"

        for cpu in processors:
            validate_model(cpu)


# ---------------------------------------------------------------------------
# TC-MEM: memory (DIMM) information tests
# ---------------------------------------------------------------------------

class TestMemory:
    """TC-MEM: Test memory information."""

    def test_memory(self, bmc_client):
        """Retrieve memory modules and validate the fields of each DIMM."""
        memories = bmc_client.get_memory()
        assert memories is not None, "get_memory() returned None"
        assert len(memories) > 0, "The server must expose at least one memory module"

        for mem in memories:
            validate_model(mem)


# ---------------------------------------------------------------------------
# TC-STORAGE: storage-controller information tests
# ---------------------------------------------------------------------------

class TestStorage:
    """TC-STORAGE: Test storage-controller information."""

    def test_storages(self, bmc_client):
        """Retrieve storage controllers and validate their fields."""
        storages = bmc_client.get_storages()
        assert storages is not None, "get_storages() returned None"

        for storage in storages:
            validate_model(storage)


# ---------------------------------------------------------------------------
# TC-GPU: GPU information tests
# ---------------------------------------------------------------------------

class TestGpu:
    """TC-GPU: Test GPU information."""

    def test_gpus(self, bmc_client):
        """Retrieve GPUs and validate their fields, or skip when absent."""
        gpus = bmc_client.get_gpus()
        assert gpus is not None, "get_gpus() returned None"

        if len(gpus) == 0:
            pytest.skip("This server has no GPU; skipping GPU validation")

        for gpu in gpus:
            validate_model(gpu)


# ---------------------------------------------------------------------------
# TC-DRIVE: physical-drive information tests
# ---------------------------------------------------------------------------

class TestDrives:
    """TC-DRIVE: Test physical-drive information."""

    def test_drives(self, bmc_client):
        """Retrieve physical drives and validate their fields."""
        drives = bmc_client.get_drives()
        assert drives is not None, "get_drives() returned None"

        for drive in drives:
            validate_model(drive)


# ---------------------------------------------------------------------------
# TC-NIC: network-adapter information tests
# ---------------------------------------------------------------------------

class TestNetworkAdapters:
    """TC-NIC: Test network-adapter information."""

    def test_network_adapters(self, bmc_client):
        """Retrieve network adapters and validate their fields."""
        nics = bmc_client.get_network_adapters()
        assert nics is not None, "get_network_adapters() returned None"

        for nic in nics:
            validate_model(nic)


# ---------------------------------------------------------------------------
# TC-PCIE: PCIe device information tests
# ---------------------------------------------------------------------------

class TestPCIeDevices:
    """TC-PCIE: Test PCIe device information."""

    def test_pcie_devices(self, bmc_client):
        """Retrieve PCIe devices and validate their fields."""
        devices = bmc_client.get_pcie_devices()
        assert devices is not None, "get_pcie_devices() returned None"

        for device in devices:
            validate_model(device)


# ---------------------------------------------------------------------------
# TC-POWER: power information tests
# ---------------------------------------------------------------------------

class TestPower:
    """TC-POWER: Test power information."""

    def test_power(self, bmc_client):
        """Retrieve power information and validate PSU fields."""
        power = bmc_client.get_power()
        assert power is not None, "get_power() returned None"

        psu_list = power.power_supplies or []
        assert len(psu_list) > 0, "power_supplies is empty"

        for psu in psu_list:
            validate_model(psu)


# ---------------------------------------------------------------------------
# TC-THERMAL: thermal information tests
# ---------------------------------------------------------------------------

class TestThermal:
    """TC-THERMAL: Test thermal information."""

    def test_thermal_fans(self, bmc_client):
        """Retrieve thermal information and validate fan fields."""
        thermal = bmc_client.get_thermal()
        assert thermal is not None, "get_thermal() returned None"

        fans = thermal.fans or []
        for fan in fans:
            validate_model(fan)

    def test_thermal_temperatures(self, bmc_client):
        """Retrieve thermal information and validate temperature sensor fields."""
        thermal = bmc_client.get_thermal()
        assert thermal is not None, "get_thermal() returned None"

        temps = thermal.temperatures or []
        for temp in temps:
            validate_model(temp)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
