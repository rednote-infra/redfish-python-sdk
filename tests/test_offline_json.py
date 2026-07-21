"""
离线模式：JSON 文件数据质量校验测试。

使用 tools/redfish_drill.py 预先采集的 JSON 数据文件，
将其反序列化为 Pydantic 模型后执行与在线模式完全相同的校验规则。

运行方式:
    # 单目录
    export REDFISH_JSON_DIR="./testdata"
    pytest tests/test_offline_json.py -v

    # 多服务器批量
    export REDFISH_JSON_DIR="./testdata_all"
    pytest tests/test_offline_json.py -v

json_loader fixture 由 conftest.py 中的 pytest_generate_tests 动态参数化，
每个 JSON 数据目录会生成一组独立的测试实例。
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
# Helper: 自动发现 System/Chassis 的 odata.id
# ---------------------------------------------------------------------------

def _get_system_odata_id(loader: RedfishJsonLoader) -> str:
    """自动发现 System 的 @odata.id，找不到则跳过测试。"""
    oid = loader.find_system_id()
    if oid is None:
        pytest.skip("未找到 System 资源的 JSON 文件")
    return oid


def _get_chassis_odata_id(loader: RedfishJsonLoader) -> str:
    """自动发现 Chassis 的 @odata.id，找不到则跳过测试。"""
    oid = loader.find_chassis_id()
    if oid is None:
        pytest.skip("未找到 Chassis 资源的 JSON 文件")
    return oid


# ---------------------------------------------------------------------------
# TC-SYSTEM: 系统信息测试
# ---------------------------------------------------------------------------

class TestOfflineSystem:
    """TC-SYSTEM: 系统信息测试（离线模式）。"""

    def test_system_info(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)
        system = json_loader.load(system_oid, System)
        if system is None:
            pytest.skip(f"System JSON 文件不存在: {system_oid}")

        # 原始 JSON key-present-but-empty 校验
        raw = json_loader.get_raw(system_oid)
        if raw:
            validate_json_key_present_but_empty(raw, "System", system_oid)

        validate_model(system)


# ---------------------------------------------------------------------------
# TC-PROC: 处理器信息测试
# ---------------------------------------------------------------------------

class TestOfflineProcessors:
    """TC-PROC: 处理器信息测试（离线模式）。"""

    def test_processors(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)

        # 尝试多种可能的集合路径
        proc_collection_oid = f"{system_oid}/Processors"
        processors = json_loader.load_collection_members(proc_collection_oid, Processor)

        if not processors:
            pytest.skip(f"Processors JSON 文件不存在或为空: {proc_collection_oid}")

        for cpu in processors:
            # 原始 JSON 校验
            raw = json_loader.get_raw(cpu.odata_id) if cpu.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "Processor", cpu.odata_id)

            validate_model(cpu)


# ---------------------------------------------------------------------------
# TC-MEM: 内存信息测试
# ---------------------------------------------------------------------------

class TestOfflineMemory:
    """TC-MEM: 内存信息测试（离线模式）。"""

    def test_memory(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)

        mem_collection_oid = f"{system_oid}/Memory"
        memories = json_loader.load_collection_members(mem_collection_oid, Memory)

        if not memories:
            pytest.skip(f"Memory JSON 文件不存在或为空: {mem_collection_oid}")

        for mem in memories:
            raw = json_loader.get_raw(mem.odata_id) if mem.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "Memory", mem.odata_id)

            validate_model(mem)


# ---------------------------------------------------------------------------
# TC-STORAGE: 存储控制器信息测试
# ---------------------------------------------------------------------------

class TestOfflineStorage:
    """TC-STORAGE: 存储控制器信息测试（离线模式）。"""

    def test_storages(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)

        storage_collection_oid = f"{system_oid}/Storage"
        storages = json_loader.load_collection_members(storage_collection_oid, Storage)

        if not storages:
            pytest.skip(f"Storage JSON 文件不存在或为空: {storage_collection_oid}")

        for storage in storages:
            raw = json_loader.get_raw(storage.odata_id) if storage.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "Storage", storage.odata_id)

            validate_model(storage)


# ---------------------------------------------------------------------------
# TC-GPU: GPU 信息测试
# ---------------------------------------------------------------------------

class TestOfflineGpu:
    """TC-GPU: GPU 信息测试（离线模式）。"""

    def test_gpus(self, json_loader: RedfishJsonLoader):
        system_oid = _get_system_odata_id(json_loader)

        # 策略 1: GraphicsControllers
        gc_oid = f"{system_oid}/GraphicsControllers"
        gpus = json_loader.load_collection_members(gc_oid, Gpu)

        # 策略 2: PCIeDevices 中名称含 GPU 的项
        if not gpus:
            chassis_oid = _get_chassis_odata_id(json_loader)
            pcie_oid = f"{chassis_oid}/PCIeDevices"
            all_pcie = json_loader.load_collection_members(pcie_oid, PCIeDevice)
            # 过滤名称含 "GPU" 的 PCIe 设备
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
            pytest.skip("未找到 GPU 资源 (GraphicsControllers 或 PCIeDevices 中无 GPU)")

        for gpu in gpus:
            validate_model(gpu)


# ---------------------------------------------------------------------------
# TC-DRIVE: 物理硬盘信息测试
# ---------------------------------------------------------------------------

class TestOfflineDrives:
    """TC-DRIVE: 物理硬盘信息测试（离线模式）。"""

    def test_drives(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        drives_collection_oid = f"{chassis_oid}/Drives"
        drives = json_loader.load_collection_members(drives_collection_oid, Drive)

        if not drives:
            # 有些厂商的 Drive 不在 Chassis/1/Drives 下，
            # 尝试从 Storage 的 Drives 链接中发现
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
            pytest.skip("Drive JSON 文件不存在或为空")

        for drive in drives:
            raw = json_loader.get_raw(drive.odata_id) if drive.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "Drive", drive.odata_id)

            validate_model(drive)


# ---------------------------------------------------------------------------
# TC-NIC: 网络适配器信息测试
# ---------------------------------------------------------------------------

class TestOfflineNetworkAdapters:
    """TC-NIC: 网络适配器信息测试（离线模式）。"""

    def test_network_adapters(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        nic_collection_oid = f"{chassis_oid}/NetworkAdapters"
        nics = json_loader.load_collection_members(nic_collection_oid, NetworkAdapter)

        if not nics:
            pytest.skip(f"NetworkAdapters JSON 文件不存在或为空: {nic_collection_oid}")

        for nic in nics:
            raw = json_loader.get_raw(nic.odata_id) if nic.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "NetworkAdapter", nic.odata_id)

            validate_model(nic)


# ---------------------------------------------------------------------------
# TC-PCIE: PCIe 设备信息测试
# ---------------------------------------------------------------------------

class TestOfflinePCIeDevices:
    """TC-PCIE: PCIe 设备信息测试（离线模式）。"""

    def test_pcie_devices(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        pcie_collection_oid = f"{chassis_oid}/PCIeDevices"
        devices = json_loader.load_collection_members(pcie_collection_oid, PCIeDevice)

        if not devices:
            pytest.skip(f"PCIeDevices JSON 文件不存在或为空: {pcie_collection_oid}")

        for device in devices:
            raw = json_loader.get_raw(device.odata_id) if device.odata_id else None
            if raw:
                validate_json_key_present_but_empty(raw, "PCIeDevice", device.odata_id)

            validate_model(device)


# ---------------------------------------------------------------------------
# TC-POWER: 电源信息测试
# ---------------------------------------------------------------------------

class TestOfflinePower:
    """TC-POWER: 电源信息测试（离线模式）。"""

    def test_power(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        power_oid = f"{chassis_oid}/Power"
        power = json_loader.load(power_oid, Power)

        if power is None:
            pytest.skip(f"Power JSON 文件不存在: {power_oid}")

        # 原始 JSON 校验
        raw = json_loader.get_raw(power_oid)
        if raw:
            validate_json_key_present_but_empty(raw, "Power", power_oid)

        psu_list = power.power_supplies or []
        if not psu_list:
            pytest.skip("power_supplies 为空")

        for psu in psu_list:
            validate_model(psu)


# ---------------------------------------------------------------------------
# TC-THERMAL: 散热信息测试
# ---------------------------------------------------------------------------

class TestOfflineThermal:
    """TC-THERMAL: 散热信息测试（离线模式）。"""

    def test_thermal_fans(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        thermal_oid = f"{chassis_oid}/Thermal"
        thermal = json_loader.load(thermal_oid, Thermal)

        if thermal is None:
            pytest.skip(f"Thermal JSON 文件不存在: {thermal_oid}")

        fans = thermal.fans or []
        for fan in fans:
            validate_model(fan)

    def test_thermal_temperatures(self, json_loader: RedfishJsonLoader):
        chassis_oid = _get_chassis_odata_id(json_loader)

        thermal_oid = f"{chassis_oid}/Thermal"
        thermal = json_loader.load(thermal_oid, Thermal)

        if thermal is None:
            pytest.skip(f"Thermal JSON 文件不存在: {thermal_oid}")

        temps = thermal.temperatures or []
        for temp in temps:
            validate_model(temp)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
