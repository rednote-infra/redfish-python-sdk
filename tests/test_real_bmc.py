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
# TC-AUTH: 登录认证测试
# ---------------------------------------------------------------------------

class TestAuth:
    """TC-AUTH: 登录认证测试。"""

    def test_login_and_root_service(self, bmc_client):
        """验证认证是否正常，root 服务文档是否可获取。"""
        root = bmc_client.root()
        assert root is not None, "root() 返回 None"
        assert root.odata_id is not None, "RootService.odata_id 为 None"
        assert root.odata_id.rstrip("/").endswith("redfish/v1"), (
            f"RootService.odata_id 不符合预期: {root.odata_id!r}"
        )

    def test_root_has_top_level_links(self, bmc_client):
        """验证 root 服务文档包含 Systems/Chassis/Managers 等顶级链接。"""
        root = bmc_client.root()
        assert root.systems is not None, "RootService.systems 链接缺失"
        assert root.chassis is not None, "RootService.chassis 链接缺失"
        assert root.managers is not None, "RootService.managers 链接缺失"


# ---------------------------------------------------------------------------
# TC-SYSTEM: 系统信息获取测试
# ---------------------------------------------------------------------------

class TestSystem:
    """TC-SYSTEM: 系统信息获取测试。"""

    def test_system_info(self, bmc_client):
        """获取系统信息并验证关键字段。"""
        system = bmc_client.get_system()
        assert system is not None, "systems.get() 返回 None"
        validate_model(system)


# ---------------------------------------------------------------------------
# TC-PROC: 处理器 (CPU) 信息测试
# ---------------------------------------------------------------------------

class TestProcessors:
    """TC-PROC: 处理器信息测试。"""

    def test_processors(self, bmc_client):
        """获取处理器列表并验证每个 CPU 的字段。"""
        processors = bmc_client.get_processors()
        assert processors is not None, "get_processors() 返回 None"
        assert len(processors) > 0, "处理器列表为空，服务器至少应有 1 个 CPU"

        for cpu in processors:
            validate_model(cpu)


# ---------------------------------------------------------------------------
# TC-MEM: 内存 (DIMM) 信息测试
# ---------------------------------------------------------------------------

class TestMemory:
    """TC-MEM: 内存信息测试。"""

    def test_memory(self, bmc_client):
        """获取内存列表并验证每个 DIMM 的字段。"""
        memories = bmc_client.get_memory()
        assert memories is not None, "get_memory() 返回 None"
        assert len(memories) > 0, "内存列表为空，服务器至少应有 1 根内存"

        for mem in memories:
            validate_model(mem)


# ---------------------------------------------------------------------------
# TC-STORAGE: 存储控制器信息测试
# ---------------------------------------------------------------------------

class TestStorage:
    """TC-STORAGE: 存储控制器信息测试。"""

    def test_storages(self, bmc_client):
        """获取存储控制器列表并验证字段。"""
        storages = bmc_client.get_storages()
        assert storages is not None, "get_storages() 返回 None"

        for storage in storages:
            validate_model(storage)


# ---------------------------------------------------------------------------
# TC-GPU: GPU 信息测试
# ---------------------------------------------------------------------------

class TestGpu:
    """TC-GPU: GPU 信息测试。"""

    def test_gpus(self, bmc_client):
        """获取 GPU 列表并验证字段（无 GPU 时跳过）。"""
        gpus = bmc_client.get_gpus()
        assert gpus is not None, "get_gpus() 返回 None"

        if len(gpus) == 0:
            pytest.skip("该服务器未配备 GPU，跳过 GPU 校验")

        for gpu in gpus:
            validate_model(gpu)


# ---------------------------------------------------------------------------
# TC-DRIVE: 物理硬盘信息测试
# ---------------------------------------------------------------------------

class TestDrives:
    """TC-DRIVE: 物理硬盘信息测试。"""

    def test_drives(self, bmc_client):
        """获取物理硬盘列表并验证字段。"""
        drives = bmc_client.get_drives()
        assert drives is not None, "get_drives() 返回 None"

        for drive in drives:
            validate_model(drive)


# ---------------------------------------------------------------------------
# TC-NIC: 网络适配器信息测试
# ---------------------------------------------------------------------------

class TestNetworkAdapters:
    """TC-NIC: 网络适配器信息测试。"""

    def test_network_adapters(self, bmc_client):
        """获取网卡列表并验证字段。"""
        nics = bmc_client.get_network_adapters()
        assert nics is not None, "get_network_adapters() 返回 None"

        for nic in nics:
            validate_model(nic)


# ---------------------------------------------------------------------------
# TC-PCIE: PCIe 设备信息测试
# ---------------------------------------------------------------------------

class TestPCIeDevices:
    """TC-PCIE: PCIe 设备信息测试。"""

    def test_pcie_devices(self, bmc_client):
        """获取 PCIe 设备列表并验证字段。"""
        devices = bmc_client.get_pcie_devices()
        assert devices is not None, "get_pcie_devices() 返回 None"

        for device in devices:
            validate_model(device)


# ---------------------------------------------------------------------------
# TC-POWER: 电源信息测试
# ---------------------------------------------------------------------------

class TestPower:
    """TC-POWER: 电源信息测试。"""

    def test_power(self, bmc_client):
        """获取电源信息并验证 PSU 字段。"""
        power = bmc_client.get_power()
        assert power is not None, "get_power() 返回 None"

        psu_list = power.power_supplies or []
        assert len(psu_list) > 0, "power_supplies 为空"

        for psu in psu_list:
            validate_model(psu)


# ---------------------------------------------------------------------------
# TC-THERMAL: 散热信息测试
# ---------------------------------------------------------------------------

class TestThermal:
    """TC-THERMAL: 散热信息测试。"""

    def test_thermal_fans(self, bmc_client):
        """获取散热信息并验证风扇字段。"""
        thermal = bmc_client.get_thermal()
        assert thermal is not None, "get_thermal() 返回 None"

        fans = thermal.fans or []
        for fan in fans:
            validate_model(fan)

    def test_thermal_temperatures(self, bmc_client):
        """获取散热信息并验证温度传感器字段。"""
        thermal = bmc_client.get_thermal()
        assert thermal is not None, "get_thermal() 返回 None"

        temps = thermal.temperatures or []
        for temp in temps:
            validate_model(temp)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
