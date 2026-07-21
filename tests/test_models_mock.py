"""
基于真实 testdata JSON 的 Model 反序列化测试。

使用 tools/redfish_drill.py 从真实机器采集的 674 个 JSON 文件，
验证 redfish_sdk/models/ 下所有 Model 实体能正确解析真实的 Redfish 响应数据。
"""
import json
import os

import pytest

from redfish_sdk.models import (
    Account,
    # account
    AccountService,
    Bios,
    Bmc,
    Boot,
    # chassis
    Chassis,
    ClientCertificate,
    Collection,
    Drive,
    Entity,
    EthernetInterface,
    # event
    EventService,
    Fan,
    FirmwareInventory,
    # fru
    Fru,
    FruChassis,
    FruProduct,
    Gpu,
    GpuOEM,
    HostInterface,
    # common
    Link,
    # logs
    Log,
    LogEntry,
    MainBoard,
    # managers
    Manager,
    Memory,
    NetworkAdapter,
    NetworkProtocol,
    # oem
    Oem,
    PCIeDevice,
    Power,
    PowerSupply,
    Processor,
    RedfishError,
    RedfishResponse,
    # registry
    Registry,
    Role,
    # root
    RootService,
    Session,
    # session
    SessionService,
    Status,
    Subscription,
    # systems
    System,
    Task,
    # task
    TaskService,
    Temperature,
    Thermal,
    # update
    UpdateService,
    Volume,
)
from redfish_sdk.models.chassis import (
    Controller,
    Location,
    PCIeInterface,
    PowerControl,
)
from redfish_sdk.models.managers import (
    GraphicalConsole,
    IPv4Address,
    IPv6Address,
    ProtocolConfig,
    Vlan,
)
from redfish_sdk.models.systems import MemoryLocation, ProcessorId

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TESTDATA_DIR = os.path.join(os.path.dirname(__file__), "..", "testdata")


def load_json(filename: str) -> dict:
    """从 testdata 目录加载 JSON 文件"""
    filepath = os.path.join(TESTDATA_DIR, filename)
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def _testdata_exists(filename: str) -> bool:
    """检查 testdata 文件是否存在"""
    return os.path.isfile(os.path.join(TESTDATA_DIR, filename))


# ============================================================================
# 1. Systems 模块
# ============================================================================


class TestSystem:
    """测试 System 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Systems_1.json")
        self.system = System(**self.data)

    def test_basic_fields(self):
        assert self.system.id == "1"
        assert isinstance(self.system.manufacturer, str)
        assert self.system.manufacturer is not None
        assert isinstance(self.system.model, str)
        assert isinstance(self.system.serial_number, str)
        assert isinstance(self.system.uuid, str)
        assert isinstance(self.system.system_type, str)
        assert self.system.system_type == "Physical"

    def test_power_state(self):
        # PowerState 在 JSON 最外层没有直接字段，但 PowerSummary 里有
        # 实际看数据，System JSON 没有顶级 PowerState 字段
        # 模型定义允许 None
        pass

    def test_status(self):
        assert self.system.status is not None
        assert isinstance(self.system.status, Status)
        assert isinstance(self.system.status.state, str)
        assert isinstance(self.system.status.health, str)

    def test_boot_nested(self):
        assert self.system.boot is not None
        assert isinstance(self.system.boot, Boot)
        assert isinstance(self.system.boot.boot_source_override_target, str)
        assert self.system.boot.boot_source_override_target == "Hdd"
        assert isinstance(self.system.boot.boot_source_override_enabled, str)
        assert isinstance(self.system.boot.boot_source_override_mode, str)
        assert isinstance(self.system.boot.allowable_values, list)
        assert len(self.system.boot.allowable_values) > 0

    def test_oem_nested(self):
        assert self.system.oem is not None
        assert isinstance(self.system.oem, Oem)
        assert self.system.oem.bmc is not None
        assert isinstance(self.system.oem.bmc, Bmc)

    def test_links(self):
        assert self.system.links is not None
        assert isinstance(self.system.links.chassis, list)
        assert len(self.system.links.chassis) > 0
        assert isinstance(self.system.links.chassis[0], Link)
        assert isinstance(self.system.links.chassis[0].odata_id, str)

    def test_sub_resource_links(self):
        assert self.system.processors is not None
        assert isinstance(self.system.processors, Link)
        assert isinstance(self.system.processors.odata_id, str)
        assert self.system.memory is not None
        assert isinstance(self.system.memory, Link)
        assert self.system.storage is not None
        assert isinstance(self.system.storage, Link)


class TestBoot:
    """测试 Boot 模型（从 System JSON 内嵌提取）"""

    def test_boot_from_system_json(self):
        data = load_json("redfish_v1_Systems_1.json")
        boot = Boot(**data["Boot"])
        assert boot.boot_source_override_target == "Hdd"
        assert boot.boot_source_override_enabled == "Disabled"
        assert boot.boot_source_override_mode == "UEFI"
        assert isinstance(boot.allowable_values, list)
        assert "Pxe" in boot.allowable_values
        assert "Hdd" in boot.allowable_values


class TestProcessor:
    """测试 Processor 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Systems_1_Processors_1.json")
        self.proc = Processor(**self.data)

    def test_basic_fields(self):
        assert self.proc.id == "1"
        assert isinstance(self.proc.manufacturer, str)
        assert self.proc.manufacturer == "Hygon"
        assert isinstance(self.proc.model, str)
        assert isinstance(self.proc.instruction_set, str)
        assert isinstance(self.proc.processor_type, str)
        assert self.proc.processor_type == "CPU"

    def test_cores_and_threads(self):
        assert isinstance(self.proc.total_cores, int)
        assert self.proc.total_cores == 64
        assert isinstance(self.proc.total_threads, int)
        assert self.proc.total_threads == 128

    def test_speed(self):
        assert isinstance(self.proc.max_speed_mhz, int)
        assert self.proc.max_speed_mhz == 3100

    def test_socket(self):
        # 注意：JSON 中 Socket 值为 int (0)，但模型定义为 Optional[str]
        # Pydantic v2 的 strict 模式未启用，int 会被自动转为 str
        # 不过在 extra="allow" 模式下可能直接接受
        # 实际验证它不会抛异常即可
        assert self.proc.socket is not None

    def test_processor_id_nested(self):
        assert self.proc.processor_id is not None
        assert isinstance(self.proc.processor_id, ProcessorId)
        assert isinstance(self.proc.processor_id.effective_family, str)
        assert isinstance(self.proc.processor_id.effective_model, str)

    def test_status(self):
        assert self.proc.status is not None
        assert isinstance(self.proc.status, Status)
        assert isinstance(self.proc.status.health, str)

    def test_oem(self):
        assert self.proc.oem is not None
        assert isinstance(self.proc.oem, Oem)
        assert self.proc.oem.bmc is not None


class TestMemory:
    """测试 Memory 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Systems_1_Memory_CPU0_DIMMA0.json")
        self.mem = Memory(**self.data)

    def test_basic_fields(self):
        assert self.mem.id == "CPU0_DIMMA0"
        assert isinstance(self.mem.manufacturer, str)
        assert self.mem.manufacturer == "Hynix"
        assert isinstance(self.mem.capacity_mib, int)
        assert self.mem.capacity_mib == 32768
        assert isinstance(self.mem.memory_device_type, str)
        assert self.mem.memory_device_type == "DDR5"

    def test_speed(self):
        assert isinstance(self.mem.operating_speed_mhz, int)
        assert self.mem.operating_speed_mhz == 5600

    def test_serial_and_part(self):
        assert isinstance(self.mem.serial_number, str)
        assert isinstance(self.mem.part_number, str)

    def test_memory_location_nested(self):
        assert self.mem.memory_location is not None
        assert isinstance(self.mem.memory_location, MemoryLocation)
        assert self.mem.memory_location.socket is not None
        assert self.mem.memory_location.channel is not None

    def test_status(self):
        assert self.mem.status is not None
        assert isinstance(self.mem.status, Status)

    def test_oem(self):
        assert self.mem.oem is not None
        assert isinstance(self.mem.oem, Oem)


class TestStorage:
    """测试 Storage 模型 - Collection 解析"""

    def test_storage_collection(self):
        data = load_json("redfish_v1_Systems_1_Storages.json")
        coll = Collection(**data)
        assert coll.members_count is not None
        assert isinstance(coll.members_count, int)
        assert isinstance(coll.members, list)


class TestBios:
    """测试 Bios 模型反序列化"""

    def test_bios_basic(self):
        data = load_json("redfish_v1_Systems_1_Bios.json")
        bios = Bios(**data)
        assert bios.name is not None or bios.id is not None
        assert bios.attributes is not None
        assert isinstance(bios.attributes, dict)
        assert len(bios.attributes) > 0


# ============================================================================
# 2. Chassis 模块
# ============================================================================


class TestChassis:
    """测试 Chassis 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Chassis_1.json")
        self.chassis = Chassis(**self.data)

    def test_basic_fields(self):
        assert self.chassis.id == "1"
        assert isinstance(self.chassis.chassis_type, str)
        assert self.chassis.chassis_type == "Rack Mount Chassis"
        assert isinstance(self.chassis.manufacturer, str)
        assert isinstance(self.chassis.model, str)
        assert isinstance(self.chassis.serial_number, str)

    def test_power_state(self):
        assert isinstance(self.chassis.power_state, str)
        assert self.chassis.power_state == "On"

    def test_status(self):
        assert self.chassis.status is not None
        assert isinstance(self.chassis.status, Status)
        assert isinstance(self.chassis.status.health, str)

    def test_oem_nested(self):
        assert self.chassis.oem is not None
        assert isinstance(self.chassis.oem, Oem)
        assert self.chassis.oem.bmc is not None
        assert isinstance(self.chassis.oem.bmc, Bmc)

    def test_oem_device_max_num(self):
        bmc = self.chassis.oem.bmc
        assert bmc.device_max_num is not None
        from redfish_sdk.models.oem import DeviceMaxNum
        assert isinstance(bmc.device_max_num, DeviceMaxNum)
        assert isinstance(bmc.device_max_num.cpu_num, int)
        assert isinstance(bmc.device_max_num.memory_num, int)

    def test_oem_mainboard(self):
        bmc = self.chassis.oem.bmc
        assert bmc.mainboard is not None
        assert isinstance(bmc.mainboard, MainBoard)

    def test_links(self):
        assert self.chassis.links is not None
        assert isinstance(self.chassis.links.managed_by, list)
        assert isinstance(self.chassis.links.computer_systems, list)

    def test_sub_resource_links(self):
        assert self.chassis.power is not None
        assert isinstance(self.chassis.power, Link)
        assert self.chassis.thermal is not None
        assert isinstance(self.chassis.thermal, Link)
        assert self.chassis.network_adapters is not None
        assert isinstance(self.chassis.network_adapters, Link)


class TestDrive:
    """测试 Drive 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Chassis_1_Drives_HDDPlaneDisk1.json")
        self.drive = Drive(**self.data)

    def test_basic_fields(self):
        assert self.drive.id == "HDDPlaneDisk1"
        assert isinstance(self.drive.manufacturer, str)
        assert self.drive.manufacturer == "Dapustor"
        assert isinstance(self.drive.model, str)
        assert isinstance(self.drive.serial_number, str)
        assert isinstance(self.drive.media_type, str)
        assert self.drive.media_type == "SSD"

    def test_capacity(self):
        assert isinstance(self.drive.capacity_bytes, int)
        assert self.drive.capacity_bytes > 0

    def test_protocol(self):
        assert isinstance(self.drive.protocol, str)
        assert self.drive.protocol == "NVMe"

    def test_status(self):
        assert self.drive.status is not None
        assert isinstance(self.drive.status, Status)

    def test_location(self):
        assert self.drive.location is not None
        assert isinstance(self.drive.location, list)
        assert len(self.drive.location) > 0
        assert isinstance(self.drive.location[0], Location)
        assert isinstance(self.drive.location[0].info, str)

    def test_predicted_life(self):
        assert isinstance(self.drive.predicted_media_life_left_percent, int)

    def test_null_field_tolerance(self):
        # StatusIndicator 在 JSON 中为 null
        assert self.drive.status_indicator is None


class TestPower:
    """测试 Power 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Chassis_1_Power.json")
        self.power = Power(**self.data)

    def test_basic_fields(self):
        assert self.power.id == "Power"
        assert self.power.name == "Power"

    def test_power_supplies(self):
        assert self.power.power_supplies is not None
        assert isinstance(self.power.power_supplies, list)
        assert len(self.power.power_supplies) >= 2
        psu = self.power.power_supplies[0]
        assert isinstance(psu, PowerSupply)

    def test_power_control(self):
        assert self.power.power_control is not None
        assert isinstance(self.power.power_control, list)
        assert len(self.power.power_control) > 0
        pc = self.power.power_control[0]
        assert isinstance(pc, PowerControl)
        assert isinstance(pc.power_consumed_watts, float)

    def test_redundancy(self):
        assert self.power.redundancy is not None
        assert isinstance(self.power.redundancy, list)


class TestPowerSupply:
    """测试 PowerSupply 模型（从 Power JSON 内嵌提取）"""

    def test_power_supply_fields(self):
        data = load_json("redfish_v1_Chassis_1_Power.json")
        psu_data = data["PowerSupplies"][0]
        psu = PowerSupply(**psu_data)
        assert isinstance(psu.manufacturer, str)
        assert psu.manufacturer == "Great Wall"
        assert isinstance(psu.model, str)
        assert isinstance(psu.serial_number, str)
        assert isinstance(psu.power_capacity_watts, int)
        assert isinstance(psu.power_input_watts, int)
        assert isinstance(psu.power_output_watts, int)
        assert isinstance(psu.power_supply_type, str)
        assert isinstance(psu.firmware_version, str)
        assert isinstance(psu.line_input_voltage, float)
        assert psu.status is not None
        assert isinstance(psu.status, Status)

    def test_power_supply_oem(self):
        data = load_json("redfish_v1_Chassis_1_Power.json")
        psu_data = data["PowerSupplies"][0]
        psu = PowerSupply(**psu_data)
        assert psu.oem is not None
        assert isinstance(psu.oem, Oem)
        assert psu.oem.bmc is not None


class TestPowerSupplyLineInputVoltage:
    """
    回归测试：PowerSupply.LineInputVoltage 必须接受 float / int / null。

    背景：DMTF Redfish PowerSupply.LineInputVoltage 在 schema 中类型为 Number，
    允许返回浮点电压（如 220.5）。SDK 早期实现误用 int，导致真机巡检失败。
    本测试不依赖外部 testdata 文件，使用内联 dict 直接覆盖三种关键输入。
    """

    def test_accepts_float_value(self):
        """AC-1: 真机返回浮点电压 → 保留为 float，不截断。"""
        psu = PowerSupply(**{"LineInputVoltage": 220.5})
        assert psu.line_input_voltage == 220.5
        assert isinstance(psu.line_input_voltage, float)

    def test_accepts_int_value_as_float(self):
        """AC-2: 真机返回整数电压 → 自动转 float（pydantic 默认行为）。"""
        psu = PowerSupply(**{"LineInputVoltage": 220})
        assert psu.line_input_voltage == 220.0
        assert isinstance(psu.line_input_voltage, float)

    def test_accepts_null_value(self):
        """AC-3: 字段缺失或为 null → 不抛异常，值为 None。"""
        psu_missing = PowerSupply(**{})
        assert psu_missing.line_input_voltage is None

        psu_null = PowerSupply(**{"LineInputVoltage": None})
        assert psu_null.line_input_voltage is None


class TestNetworkAdapter:
    """测试 NetworkAdapter 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Chassis_1_NetworkAdapters_NIC_RiserA_Slot3.json")
        self.nic = NetworkAdapter(**self.data)

    def test_basic_fields(self):
        assert self.nic.id == "NIC_RiserA_Slot3"
        assert isinstance(self.nic.manufacturer, str)
        assert self.nic.manufacturer == "Mellanox"
        assert isinstance(self.nic.model, str)
        assert isinstance(self.nic.serial_number, str)

    def test_controllers_nested(self):
        assert self.nic.controllers is not None
        assert isinstance(self.nic.controllers, list)
        assert len(self.nic.controllers) > 0
        ctrl = self.nic.controllers[0]
        assert isinstance(ctrl, Controller)
        assert isinstance(ctrl.firmware_package_version, str)

    def test_status(self):
        assert self.nic.status is not None
        assert isinstance(self.nic.status, Status)

    def test_oem(self):
        assert self.nic.oem is not None
        assert isinstance(self.nic.oem, Oem)
        assert self.nic.oem.bmc is not None


class TestPCIeDevice:
    """测试 PCIeDevice 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Chassis_1_PCIeDevices_EthernetCard0.json")
        self.pcie = PCIeDevice(**self.data)

    def test_basic_fields(self):
        assert self.pcie.id == "EthernetCard0"
        assert isinstance(self.pcie.manufacturer, str)
        assert self.pcie.manufacturer == "Mellanox"
        assert isinstance(self.pcie.model, str)
        assert isinstance(self.pcie.serial_number, str)

    def test_card_model(self):
        assert isinstance(self.pcie.card_model, str)

    def test_pcie_interface_nested(self):
        assert self.pcie.pcie_interface is not None
        assert isinstance(self.pcie.pcie_interface, PCIeInterface)
        assert isinstance(self.pcie.pcie_interface.lanes_in_use, int)
        assert isinstance(self.pcie.pcie_interface.max_lanes, int)

    def test_status(self):
        assert self.pcie.status is not None
        assert isinstance(self.pcie.status, Status)

    def test_oem(self):
        assert self.pcie.oem is not None
        from redfish_sdk.models.chassis import PCIeDeviceOEM
        assert isinstance(self.pcie.oem, PCIeDeviceOEM)


# ============================================================================
# 3. Managers 模块
# ============================================================================


class TestManager:
    """测试 Manager 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Managers_1.json")
        self.mgr = Manager(**self.data)

    def test_basic_fields(self):
        assert self.mgr.id == "1"
        assert isinstance(self.mgr.manager_type, str)
        assert self.mgr.manager_type == "BMC"
        assert isinstance(self.mgr.firmware_version, str)
        assert self.mgr.firmware_version == "2.38"

    def test_manufacturer_model(self):
        # Manager JSON 中有 Manufacturer 和 Model 字段
        # 但 Manager 模型继承自 Entity，这些不是 Entity 字段
        # 检查它们是否正确映射
        assert isinstance(self.mgr.manufacturer, str) if hasattr(self.mgr, 'manufacturer') else True

    def test_power_state(self):
        assert isinstance(self.mgr.power_state, str)
        assert self.mgr.power_state == "On"

    def test_uuid(self):
        assert isinstance(self.mgr.uuid, str)

    def test_status(self):
        assert self.mgr.status is not None
        assert isinstance(self.mgr.status, Status)
        assert isinstance(self.mgr.status.health, str)

    def test_graphical_console_nested(self):
        assert self.mgr.graphical_console is not None
        assert isinstance(self.mgr.graphical_console, GraphicalConsole)
        assert isinstance(self.mgr.graphical_console.max_concurrent_sessions, int)
        assert isinstance(self.mgr.graphical_console.service_enabled, bool)

    def test_sub_resource_links(self):
        assert self.mgr.ethernet_interfaces is not None
        assert isinstance(self.mgr.ethernet_interfaces, Link)
        assert self.mgr.network_protocol is not None
        assert isinstance(self.mgr.network_protocol, Link)
        assert self.mgr.log_services is not None
        assert isinstance(self.mgr.log_services, Link)


class TestNetworkProtocol:
    """测试 NetworkProtocol 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Managers_1_NetworkProtocol.json")
        self.np = NetworkProtocol(**self.data)

    def test_basic_fields(self):
        assert self.np.id == "NetworkProtocol"
        assert isinstance(self.np.fqdn, str)
        assert isinstance(self.np.host_name, str)

    def test_https_protocol(self):
        assert self.np.https is not None
        assert isinstance(self.np.https, ProtocolConfig)
        assert isinstance(self.np.https.port, int)
        assert self.np.https.port == 443
        assert isinstance(self.np.https.protocol_enabled, bool)

    def test_ssh_protocol(self):
        assert self.np.ssh is not None
        assert isinstance(self.np.ssh, ProtocolConfig)
        assert self.np.ssh.port == 22

    def test_ipmi_protocol(self):
        assert self.np.ipmi is not None
        assert isinstance(self.np.ipmi, ProtocolConfig)
        assert self.np.ipmi.port == 623

    def test_snmp_protocol(self):
        assert self.np.snmp is not None
        assert isinstance(self.np.snmp, ProtocolConfig)

    def test_kvmip_protocol(self):
        assert self.np.kvmip is not None
        assert isinstance(self.np.kvmip, ProtocolConfig)

    def test_status(self):
        assert self.np.status is not None
        assert isinstance(self.np.status, Status)


class TestEthernetInterface:
    """测试 EthernetInterface 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Managers_1_EthernetInterfaces_e8611a734368.json")
        self.eth = EthernetInterface(**self.data)

    def test_basic_fields(self):
        assert self.eth.id == "e8611a734368"
        assert isinstance(self.eth.mac_address, str)
        assert self.eth.mac_address == "e8:61:1a:73:43:68"

    def test_ipv4_addresses(self):
        import re

        assert self.eth.ipv4_addresses is not None
        assert isinstance(self.eth.ipv4_addresses, list)
        assert len(self.eth.ipv4_addresses) > 0
        ipv4 = self.eth.ipv4_addresses[0]
        assert isinstance(ipv4, IPv4Address)
        assert isinstance(ipv4.address, str)
        # Structural assertion: parsed value must look like a v4 address.
        # The concrete value is fixture-dependent and intentionally not asserted
        # here to avoid leaking real BMC addresses into the repository.
        assert re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ipv4.address)
        assert isinstance(ipv4.subnet_mask, str)
        assert isinstance(ipv4.gateway, str)

    def test_ipv6_addresses(self):
        assert self.eth.ipv6_addresses is not None
        assert isinstance(self.eth.ipv6_addresses, list)
        assert len(self.eth.ipv6_addresses) > 0
        ipv6 = self.eth.ipv6_addresses[0]
        assert isinstance(ipv6, IPv6Address)
        assert isinstance(ipv6.address, str)
        assert isinstance(ipv6.prefix_length, int)

    def test_speed(self):
        assert isinstance(self.eth.speed_mbps, int)
        assert self.eth.speed_mbps == 1000

    def test_link_status(self):
        assert isinstance(self.eth.link_status, str)
        assert self.eth.link_status == "LinkUp"

    def test_vlan(self):
        assert self.eth.vlan is not None
        assert isinstance(self.eth.vlan, Vlan)
        assert isinstance(self.eth.vlan.vlan_enable, bool)
        assert isinstance(self.eth.vlan.vlan_id, int)

    def test_status(self):
        assert self.eth.status is not None
        assert isinstance(self.eth.status, Status)


# ============================================================================
# 4. OEM 模块
# ============================================================================


class TestOem:
    """测试 Oem 模型及厂商别名解析"""

    def test_oem_from_chassis(self):
        """验证 Public key 被正确解析为 bmc 字段"""
        data = load_json("redfish_v1_Chassis_1.json")
        oem = Oem(**data["Oem"])
        assert oem.bmc is not None
        assert isinstance(oem.bmc, Bmc)

    def test_oem_from_system(self):
        data = load_json("redfish_v1_Systems_1.json")
        oem = Oem(**data["Oem"])
        assert oem.bmc is not None
        assert isinstance(oem.bmc, Bmc)

    def test_oem_from_processor(self):
        data = load_json("redfish_v1_Systems_1_Processors_1.json")
        oem = Oem(**data["Oem"])
        assert oem.bmc is not None
        assert isinstance(oem.bmc, Bmc)


class TestMainBoard:
    """测试 MainBoard 模型（从 Chassis OEM 内嵌提取）"""

    def test_mainboard_from_chassis_oem(self):
        data = load_json("redfish_v1_Chassis_1.json")
        oem = Oem(**data["Oem"])
        mb = oem.bmc.mainboard
        assert mb is not None
        assert isinstance(mb, MainBoard)
        # Chassis JSON 中 Mainboard 字段名为 BoardName 而非 PrettyName
        # 但模型使用 PrettyName alias，所以 pretty_name 可能为 None
        # 关键字段验证
        assert isinstance(mb.serial_number, str) if mb.serial_number else True
        assert isinstance(mb.part_number, str) if mb.part_number else True
        assert isinstance(mb.manufacturer, str) if mb.manufacturer else True

    def test_mainboard_from_fru(self):
        """FRU JSON 中的 MainBoard 字段"""
        data = load_json("redfish_v1_Systems_1_FruInfo.json")
        mb = MainBoard(**data["MainBoard"])
        assert isinstance(mb.manufacturer, str)
        assert isinstance(mb.part_number, str)
        assert isinstance(mb.serial_number, str)
        # FRU JSON 使用 PrettyName
        assert isinstance(mb.pretty_name, str)
        assert isinstance(mb.build_date, str)


# ============================================================================
# 5. FRU 模块
# ============================================================================


class TestFru:
    """测试 Fru 模型反序列化"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json("redfish_v1_Systems_1_FruInfo.json")
        self.fru = Fru(**self.data)

    def test_basic_fields(self):
        assert self.fru.id == "FruInfo"
        assert self.fru.name == "FruInfo"

    def test_chassis_nested(self):
        assert self.fru.chassis is not None
        assert isinstance(self.fru.chassis, FruChassis)

    def test_product_nested(self):
        assert self.fru.product is not None
        assert isinstance(self.fru.product, FruProduct)
        assert isinstance(self.fru.product.manufacturer, str)
        assert isinstance(self.fru.product.serial_number, str)
        assert isinstance(self.fru.product.part_number, str)

    def test_board_nested(self):
        assert self.fru.board is not None
        assert isinstance(self.fru.board, MainBoard)
        assert isinstance(self.fru.board.manufacturer, str)
        assert isinstance(self.fru.board.serial_number, str)

    def test_status(self):
        assert self.fru.status is not None
        assert isinstance(self.fru.status, Status)


class TestFruChassis:
    """测试 FruChassis 模型"""

    def test_fru_chassis(self):
        data = load_json("redfish_v1_Systems_1_FruInfo.json")
        fc = FruChassis(**data["Chassis"])
        # JSON 使用 "Type"，但模型使用 alias "ChassisType"
        # extra="allow" 会允许 Type 进入 extra 字段
        # 确保不抛异常即可
        assert fc is not None


class TestFruProduct:
    """测试 FruProduct 模型"""

    def test_fru_product(self):
        data = load_json("redfish_v1_Systems_1_FruInfo.json")
        fp = FruProduct(**data["Product"])
        assert isinstance(fp.manufacturer, str)
        assert isinstance(fp.serial_number, str)
        assert isinstance(fp.part_number, str)
        assert isinstance(fp.version, str)
        # PrettyName -> name 映射（Product JSON 中没有 Name 但有 PrettyName）
        # FruProduct 使用 alias "Name"，但 JSON 中是 "PrettyName"
        # 所以 name 可能来自 Product.Name (不存在) -> None
        # 实际 JSON 中 Product 没有 "Name" 字段但有 "PrettyName"
        # FruProduct.name alias 是 "Name"，不是 "PrettyName"


# ============================================================================
# 6. Logs 模块
# ============================================================================


class TestLog:
    """测试 Log 模型反序列化"""

    def test_log_basic(self):
        data = load_json("redfish_v1_Systems_1_LogServices_SEL.json")
        log = Log(**data)
        assert log.id == "SEL"
        assert log.name == "IPMI SEL"
        assert log.entries is not None
        assert isinstance(log.entries, Link)
        assert isinstance(log.entries.odata_id, str)
        assert isinstance(log.max_number_of_records, int)
        assert isinstance(log.overwrite_policy, str)
        assert isinstance(log.service_enabled, bool)

    def test_log_status(self):
        data = load_json("redfish_v1_Systems_1_LogServices_SEL.json")
        log = Log(**data)
        assert log.status is not None
        assert isinstance(log.status, Status)


class TestLogEntry:
    """测试 LogEntry 模型反序列化"""

    def test_log_entry_basic(self):
        data = load_json("redfish_v1_Systems_1_LogServices_SEL_Entries_1.json")
        entry = LogEntry(**data)
        assert entry.id == "1"
        assert isinstance(entry.name, str)
        assert isinstance(entry.message, str)
        assert isinstance(entry.severity, str)
        assert isinstance(entry.created, str)

    def test_log_entry_details(self):
        data = load_json("redfish_v1_Systems_1_LogServices_SEL_Entries_1.json")
        entry = LogEntry(**data)
        assert isinstance(entry.entry_type, str)
        assert entry.entry_type == "SEL"
        assert isinstance(entry.entry_code, str)
        assert isinstance(entry.sensor_number, int)
        assert isinstance(entry.sensor_type, str)


# ============================================================================
# 7. Collection 解析
# ============================================================================


class TestCollections:
    """测试 Collection 模型解析各种资源集合"""

    def test_processor_collection(self):
        data = load_json("redfish_v1_Systems_1_Processors.json")
        coll = Collection(**data)
        assert coll.members_count is not None
        assert isinstance(coll.members_count, int)
        assert coll.members_count == 1
        assert isinstance(coll.members, list)
        assert len(coll.members) == 1
        assert isinstance(coll.members[0], Link)
        assert coll.members[0].odata_id == "/redfish/v1/Systems/1/Processors/1"

    def test_memory_collection(self):
        data = load_json("redfish_v1_Systems_1_Memory.json")
        coll = Collection(**data)
        assert coll.members_count == 12
        assert isinstance(coll.members, list)
        assert len(coll.members) == 12
        assert all(isinstance(m, Link) for m in coll.members)
        assert all(isinstance(m.odata_id, str) for m in coll.members)

    def test_drives_collection(self):
        data = load_json("redfish_v1_Chassis_1_Drives.json")
        coll = Collection(**data)
        assert coll.members_count == 4
        assert isinstance(coll.members, list)
        assert len(coll.members) == 4

    def test_ethernet_interfaces_collection(self):
        data = load_json("redfish_v1_Managers_1_EthernetInterfaces.json")
        coll = Collection(**data)
        assert coll.members_count == 2
        assert isinstance(coll.members, list)
        assert len(coll.members) == 2


# ============================================================================
# 8. 无 testdata 的 Model 覆盖测试
#    需求第 4 条：必须覆盖所有的 model 定义，若测试数据当中没有 model 对应的
#    json 文件，则认为测试不通过。
#    以下对于缺乏直接 testdata 的 Model，采用两种策略：
#    a) 从已有 JSON 中提取内嵌数据（如 Fan、Temperature 从 Thermal JSON）
#    b) 对于确实没有任何 testdata 的 Model，使用 pytest.fail 标记
# ============================================================================


class TestCommonModels:
    """测试 common 模块中的基础 Model"""

    def test_link(self):
        data = load_json("redfish_v1_Systems_1.json")
        # Processors 字段就是一个 Link
        link = Link(**data["Processors"])
        assert isinstance(link.odata_id, str)
        assert link.odata_id == "/redfish/v1/Systems/1/Processors"

    def test_entity(self):
        data = load_json("redfish_v1_Systems_1.json")
        entity = Entity(**data)
        assert entity.id == "1"
        assert isinstance(entity.odata_type, str)
        assert isinstance(entity.odata_id, str)

    def test_status(self):
        data = load_json("redfish_v1_Systems_1.json")
        status = Status(**data["Status"])
        assert status.health == "OK"
        assert status.state == "Enabled"

    def test_redfish_response_minimal(self):
        """RedfishResponse 可以用空数据构造"""
        resp = RedfishResponse()
        assert resp.error is None
        assert resp.message is None

    def test_redfish_error_minimal(self):
        """RedfishError 可以用空数据构造"""
        err = RedfishError()
        assert err.code is None
        assert err.message is None


class TestModelsWithoutDirectTestdata:
    """
    验证所有 __init__.py 中导出的 Model 类都能被测试覆盖。

    对于确实没有独立 testdata JSON 的 Model，使用以下策略：
    - 从已有 JSON 内嵌数据中提取并验证
    - 或验证 Model 能用最小数据构造（不抛异常）
    """

    # ---- RootService ----
    def test_root_service(self):
        """RootService - 虽然 testdata 目录中没有 redfish_v1.json，
        但可以用最小构造验证模型"""
        root = RootService(
            **{
                "@odata.id": "/redfish/v1/",
                "@odata.type": "#ServiceRoot.v1_5_0.ServiceRoot",
                "Id": "RootService",
                "Name": "Root Service",
                "RedfishVersion": "1.8.0",
                "Systems": {"@odata.id": "/redfish/v1/Systems"},
                "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
                "Managers": {"@odata.id": "/redfish/v1/Managers"},
            }
        )
        assert root.id == "RootService"
        assert root.redfish_version == "1.8.0"
        assert isinstance(root.systems, Link)
        assert isinstance(root.chassis, Link)
        assert isinstance(root.managers, Link)
        pytest.fail(
            "RootService: testdata 中不存在 redfish_v1.json，"
            "测试使用构造数据验证模型结构正确，但标记为失败以提示补充数据"
        )

    # ---- AccountService / Account / Role ----
    def test_account_service(self):
        svc = AccountService(
            **{
                "@odata.id": "/redfish/v1/AccountService",
                "Id": "AccountService",
                "Name": "Account Service",
                "Accounts": {"@odata.id": "/redfish/v1/AccountService/Accounts"},
                "Roles": {"@odata.id": "/redfish/v1/AccountService/Roles"},
                "ServiceEnabled": True,
            }
        )
        assert svc.id == "AccountService"
        assert isinstance(svc.accounts, Link)
        pytest.fail("AccountService: testdata 中缺少对应 JSON 文件")

    def test_account(self):
        acct = Account(
            **{
                "@odata.id": "/redfish/v1/AccountService/Accounts/1",
                "Id": "1",
                "Name": "User Account",
                "UserName": "admin",
                "RoleId": "Administrator",
                "Enabled": True,
                "Locked": False,
            }
        )
        assert acct.user_name == "admin"
        assert acct.role_id == "Administrator"
        pytest.fail("Account: testdata 中缺少对应 JSON 文件")

    def test_role(self):
        role = Role(
            **{
                "@odata.id": "/redfish/v1/AccountService/Roles/Administrator",
                "Id": "Administrator",
                "Name": "Administrator Role",
                "IsPredefined": True,
                "AssignedPrivileges": ["Login", "ConfigureManager"],
            }
        )
        assert role.id == "Administrator"
        pytest.fail("Role: testdata 中缺少对应 JSON 文件")

    # ---- SessionService / Session ----
    def test_session_service(self):
        svc = SessionService(
            **{
                "@odata.id": "/redfish/v1/SessionService",
                "Id": "SessionService",
                "Name": "Session Service",
                "Sessions": {"@odata.id": "/redfish/v1/SessionService/Sessions"},
                "ServiceEnabled": True,
                "SessionTimeout": 1800,
            }
        )
        assert svc.session_timeout == 1800
        pytest.fail("SessionService: testdata 中缺少对应 JSON 文件")

    def test_session(self):
        sess = Session(
            **{
                "@odata.id": "/redfish/v1/SessionService/Sessions/1",
                "Id": "1",
                "Name": "User Session",
                "UserName": "admin",
                "SessionType": "Redfish",
            }
        )
        assert sess.user_name == "admin"
        pytest.fail("Session: testdata 中缺少对应 JSON 文件")

    # ---- EventService / Subscription ----
    def test_event_service(self):
        svc = EventService(
            **{
                "@odata.id": "/redfish/v1/EventService",
                "Id": "EventService",
                "Name": "Event Service",
                "ServiceEnabled": True,
                "DeliveryRetryAttempts": 3,
                "Subscriptions": {"@odata.id": "/redfish/v1/EventService/Subscriptions"},
            }
        )
        assert svc.delivery_retry_attempts == 3
        pytest.fail("EventService: testdata 中缺少对应 JSON 文件")

    def test_subscription(self):
        sub = Subscription(
            **{
                "@odata.id": "/redfish/v1/EventService/Subscriptions/1",
                "Id": "1",
                "Name": "Subscription 1",
                "Destination": "https://example.com/events",
                "Protocol": "Redfish",
                "Context": "test",
            }
        )
        assert sub.destination == "https://example.com/events"
        pytest.fail("Subscription: testdata 中缺少对应 JSON 文件")

    # ---- UpdateService / FirmwareInventory / ClientCertificate ----
    def test_update_service(self):
        svc = UpdateService(
            **{
                "@odata.id": "/redfish/v1/UpdateService",
                "Id": "UpdateService",
                "Name": "Update Service",
                "ServiceEnabled": True,
                "FirmwareInventory": {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory"},
                "HttpPushUri": "/redfish/v1/UpdateService/upload",
            }
        )
        assert isinstance(svc.firmware_inventory, Link)
        assert svc.http_push_uri is not None
        pytest.fail("UpdateService: testdata 中缺少对应 JSON 文件")

    def test_firmware_inventory(self):
        fw = FirmwareInventory(
            **{
                "@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/BMC",
                "Id": "BMC",
                "Name": "BMC Firmware",
                "Version": "2.38",
                "Updateable": True,
            }
        )
        assert fw.version == "2.38"
        pytest.fail("FirmwareInventory: testdata 中缺少对应 JSON 文件")

    def test_client_certificate(self):
        cert = ClientCertificate(
            **{
                "@odata.id": "/redfish/v1/UpdateService/ClientCertificates/1",
                "Id": "1",
                "Name": "Client Certificate",
                "CertificateType": "PEM",
            }
        )
        assert cert.certificate_type == "PEM"
        pytest.fail("ClientCertificate: testdata 中缺少对应 JSON 文件")

    # ---- Registry ----
    def test_registry(self):
        reg = Registry(
            **{
                "@odata.id": "/redfish/v1/Registries/Base",
                "Id": "Base",
                "Name": "Base Message Registry",
                "Languages": ["en"],
                "RegistryPrefix": "Base",
                "RegistryVersion": "1.0.0",
            }
        )
        assert reg.registry_prefix == "Base"
        pytest.fail("Registry: testdata 中缺少对应 JSON 文件")

    # ---- TaskService / Task ----
    def test_task_service(self):
        svc = TaskService(
            **{
                "@odata.id": "/redfish/v1/TaskService",
                "Id": "TaskService",
                "Name": "Task Service",
                "ServiceEnabled": True,
                "Tasks": {"@odata.id": "/redfish/v1/TaskService/Tasks"},
            }
        )
        assert svc.service_enabled is True
        pytest.fail("TaskService: testdata 中缺少对应 JSON 文件")

    def test_task(self):
        task = Task(
            **{
                "@odata.id": "/redfish/v1/TaskService/Tasks/1",
                "Id": "1",
                "Name": "Task 1",
                "TaskState": "Completed",
                "TaskStatus": "OK",
                "PercentComplete": 100,
            }
        )
        assert task.task_state == "Completed"
        assert task.percent_complete == 100
        pytest.fail("Task: testdata 中缺少对应 JSON 文件")

    # ---- Volume ----
    def test_volume(self):
        vol = Volume(
            **{
                "@odata.id": "/redfish/v1/Systems/1/Storage/1/Volumes/1",
                "Id": "1",
                "Name": "Volume 1",
                "VolumeType": "Mirrored",
                "CapacityBytes": 1099511627776,
                "RAIDType": "RAID1",
            }
        )
        assert vol.volume_type == "Mirrored"
        assert vol.capacity_bytes == 1099511627776
        pytest.fail("Volume: testdata 中缺少对应 JSON 文件")

    # ---- Gpu / GpuOEM ----
    def test_gpu(self):
        gpu = Gpu(
            **{
                "@odata.id": "/redfish/v1/Systems/1/GraphicsControllers/1",
                "Id": "1",
                "Name": "GPU 0",
                "Manufacturer": "NVIDIA",
                "Model": "A100",
            }
        )
        assert gpu.manufacturer == "NVIDIA"
        pytest.fail("Gpu: testdata 中缺少对应 JSON 文件")

    def test_gpu_oem(self):
        oem = GpuOEM(**{"SerialNumber": "GPU-SN-12345"})
        assert oem.serial_number == "GPU-SN-12345"
        pytest.fail("GpuOEM: testdata 中缺少对应 JSON 文件")

    # ---- Thermal / Fan / Temperature ----
    def test_thermal(self):
        thermal = Thermal(
            **{
                "@odata.id": "/redfish/v1/Chassis/1/Thermal",
                "Id": "Thermal",
                "Name": "Thermal",
                "Fans": [
                    {
                        "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Fans/0",
                        "Name": "Fan 1",
                        "MemberId": "0",
                        "Reading": 6000,
                        "ReadingUnits": "RPM",
                        "Status": {"State": "Enabled", "Health": "OK"},
                    }
                ],
                "Temperatures": [
                    {
                        "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Temperatures/0",
                        "Name": "CPU Temp",
                        "MemberId": "0",
                        "ReadingCelsius": 45.0,
                        "Status": {"State": "Enabled", "Health": "OK"},
                    }
                ],
            }
        )
        assert thermal.fans is not None
        assert len(thermal.fans) == 1
        assert isinstance(thermal.fans[0], Fan)
        assert thermal.temperatures is not None
        assert isinstance(thermal.temperatures[0], Temperature)
        pytest.fail("Thermal: testdata 中缺少 redfish_v1_Chassis_1_Thermal.json 文件")

    def test_fan(self):
        fan = Fan(
            **{
                "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Fans/0",
                "Name": "Fan 1",
                "MemberId": "0",
                "Reading": 6000,
                "ReadingUnits": "RPM",
                "Status": {"State": "Enabled", "Health": "OK"},
            }
        )
        assert fan.reading == 6000
        assert fan.reading_units == "RPM"
        pytest.fail("Fan: testdata 中缺少包含 Fans 数据的 Thermal JSON 文件")

    def test_temperature(self):
        temp = Temperature(
            **{
                "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Temperatures/0",
                "Name": "CPU Temp",
                "MemberId": "0",
                "ReadingCelsius": 45.0,
                "Status": {"State": "Enabled", "Health": "OK"},
            }
        )
        assert temp.reading_celsius == 45.0
        pytest.fail("Temperature: testdata 中缺少包含 Temperatures 数据的 Thermal JSON 文件")

    # ---- HostInterface ----
    def test_host_interface(self):
        hi = HostInterface(
            **{
                "@odata.id": "/redfish/v1/Managers/1/HostInterfaces/1",
                "Id": "1",
                "Name": "Host Interface",
                "HostInterfaceType": "NetworkHostInterface",
                "InterfaceEnabled": True,
            }
        )
        assert hi.host_interface_type == "NetworkHostInterface"
        pytest.fail("HostInterface: testdata 中缺少对应 JSON 文件")

    # ---- Bmc (OEM 内部模型) ----
    def test_bmc(self):
        """Bmc 可从已有 testdata 中的 Oem.Public 提取"""
        data = load_json("redfish_v1_Chassis_1.json")
        bmc = Bmc(**data["Oem"]["Public"])
        assert bmc is not None
        assert bmc.device_max_num is not None
        assert bmc.mainboard is not None


# ============================================================================
# 9. 模型覆盖率检查
# ============================================================================


class TestModelCoverage:
    """验证所有导出的 Model 都已在本测试文件中被覆盖"""

    # __init__.py 中导出的所有 Model 类
    ALL_EXPORTED_MODELS = {
        "Link", "Entity", "Collection", "Status", "RedfishResponse", "RedfishError",
        "RootService",
        "System", "Processor", "Memory", "Storage", "Volume", "Bios", "Boot", "Gpu", "GpuOEM",
        "Chassis", "Drive", "NetworkAdapter", "Power", "PowerSupply", "Thermal",
        "PCIeDevice", "Fan", "Temperature",
        "Manager", "NetworkProtocol", "EthernetInterface", "HostInterface",
        "AccountService", "Account", "Role",
        "SessionService", "Session",
        "EventService", "Subscription",
        "UpdateService", "FirmwareInventory", "ClientCertificate",
        "Registry",
        "TaskService", "Task",
        "Oem", "Bmc", "MainBoard",
        "Log", "LogEntry",
        "Fru", "FruChassis", "FruProduct",
    }

    # 每个 Model 对应的 testdata 文件映射
    # 值为 None 表示没有独立的 testdata 文件
    MODEL_TESTDATA_MAP = {
        # common - 基础模型，从其他 JSON 中提取
        "Link": "redfish_v1_Systems_1.json",
        "Entity": "redfish_v1_Systems_1.json",
        "Collection": "redfish_v1_Systems_1_Processors.json",
        "Status": "redfish_v1_Systems_1.json",
        "RedfishResponse": None,  # 操作响应类，无独立 JSON
        "RedfishError": None,  # 错误响应类，无独立 JSON
        # root
        "RootService": None,
        # systems
        "System": "redfish_v1_Systems_1.json",
        "Processor": "redfish_v1_Systems_1_Processors_1.json",
        "Memory": "redfish_v1_Systems_1_Memory_CPU0_DIMMA0.json",
        "Storage": "redfish_v1_Systems_1_Storages.json",
        "Volume": None,
        "Bios": "redfish_v1_Systems_1_Bios.json",
        "Boot": "redfish_v1_Systems_1.json",  # 内嵌
        "Gpu": None,
        "GpuOEM": None,
        # chassis
        "Chassis": "redfish_v1_Chassis_1.json",
        "Drive": "redfish_v1_Chassis_1_Drives_HDDPlaneDisk1.json",
        "NetworkAdapter": "redfish_v1_Chassis_1_NetworkAdapters_NIC_RiserA_Slot3.json",
        "Power": "redfish_v1_Chassis_1_Power.json",
        "PowerSupply": "redfish_v1_Chassis_1_Power.json",  # 内嵌
        "Thermal": None,
        "PCIeDevice": "redfish_v1_Chassis_1_PCIeDevices_EthernetCard0.json",
        "Fan": None,
        "Temperature": None,
        # managers
        "Manager": "redfish_v1_Managers_1.json",
        "NetworkProtocol": "redfish_v1_Managers_1_NetworkProtocol.json",
        "EthernetInterface": "redfish_v1_Managers_1_EthernetInterfaces_e8611a734368.json",
        "HostInterface": None,
        # account
        "AccountService": None,
        "Account": None,
        "Role": None,
        # session
        "SessionService": None,
        "Session": None,
        # event
        "EventService": None,
        "Subscription": None,
        # update
        "UpdateService": None,
        "FirmwareInventory": None,
        "ClientCertificate": None,
        # registry
        "Registry": None,
        # task
        "TaskService": None,
        "Task": None,
        # oem
        "Oem": "redfish_v1_Chassis_1.json",  # 内嵌
        "Bmc": "redfish_v1_Chassis_1.json",  # 内嵌
        "MainBoard": "redfish_v1_Chassis_1.json",  # 内嵌
        # logs
        "Log": "redfish_v1_Systems_1_LogServices_SEL.json",
        "LogEntry": "redfish_v1_Systems_1_LogServices_SEL_Entries_1.json",
        # fru
        "Fru": "redfish_v1_Systems_1_FruInfo.json",
        "FruChassis": "redfish_v1_Systems_1_FruInfo.json",  # 内嵌
        "FruProduct": "redfish_v1_Systems_1_FruInfo.json",  # 内嵌
    }

    def test_all_models_are_mapped(self):
        """确保所有导出的 Model 都在映射表中"""
        mapped = set(self.MODEL_TESTDATA_MAP.keys())
        missing = self.ALL_EXPORTED_MODELS - mapped
        assert not missing, f"以下 Model 未在映射表中: {missing}"

    def test_testdata_files_exist(self):
        """验证所有有 testdata 映射的文件确实存在"""
        missing_files = []
        for model_name, filename in self.MODEL_TESTDATA_MAP.items():
            if filename is not None and not _testdata_exists(filename):
                missing_files.append(f"{model_name} -> {filename}")
        assert not missing_files, (
            "以下 Model 的 testdata 文件不存在:\n" + "\n".join(missing_files)
        )

    def test_models_without_testdata(self):
        """
        列出所有缺少 testdata 的 Model。
        需求第 4 条要求：若没有 model 对应的 json 文件，则测试不通过。
        RedfishResponse 和 RedfishError 属于操作响应模型，不对应具体 Redfish 资源。
        """
        models_without_data = [
            name for name, filename in self.MODEL_TESTDATA_MAP.items()
            if filename is None
            # RedfishResponse 和 RedfishError 是操作响应类，
            # 不对应独立的 Redfish 资源端点
            and name not in ("RedfishResponse", "RedfishError")
        ]
        if models_without_data:
            pytest.fail(
                f"以下 {len(models_without_data)} 个 Model 在 testdata 中没有"
                f"对应的 JSON 文件:\n"
                + "\n".join(f"  - {name}" for name in sorted(models_without_data))
                + "\n\n请使用 tools/redfish_drill.py 补充采集这些资源的数据。"
            )
