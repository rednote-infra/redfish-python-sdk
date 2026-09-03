"""
Unit tests for the Redfish SDK models.
Tests data model creation, field mapping, and OEM vendor alias resolution.
"""
import pytest

from redfish_sdk.models.account import Account
from redfish_sdk.models.chassis import Power
from redfish_sdk.models.common import Collection, Entity, Link
from redfish_sdk.models.drive import Drive
from redfish_sdk.models.oem import Oem
from redfish_sdk.models.session import Session
from redfish_sdk.models.systems import Memory, Processor, System
from redfish_sdk.models.thermal import Fan


class TestLink:
    def test_basic_link(self):
        link = Link(**{"@odata.id": "/redfish/v1/Systems"})
        assert link.odata_id == "/redfish/v1/Systems"

    def test_link_extra_fields_ignored(self):
        link = Link(**{"@odata.id": "/redfish/v1/Systems", "extra": "value"})
        assert link.odata_id == "/redfish/v1/Systems"


class TestEntity:
    def test_entity_fields(self):
        entity = Entity(**{
            "@odata.id": "/redfish/v1/Systems/1",
            "@odata.type": "#ComputerSystem.v1_0_0.ComputerSystem",
            "Id": "1",
            "Name": "Server",
            "Description": "A test server",
            "@odata.etag": "W/\"abc123\"",
        })
        assert entity.odata_id == "/redfish/v1/Systems/1"
        assert entity.id == "1"
        assert entity.name == "Server"
        assert entity.odata_etag == "W/\"abc123\""


class TestSystem:
    def test_system_basic_fields(self):
        data = {
            "@odata.id": "/redfish/v1/Systems/1",
            "Id": "1",
            "Name": "Server",
            "Manufacturer": "Dell",
            "Model": "PowerEdge R740",
            "SerialNumber": "SN123456",
            "BiosVersion": "2.14.1",
            "PowerState": "On",
            "UUID": "12345678-1234-1234-1234-123456789abc",
        }
        system = System(**data)
        assert system.manufacturer == "Dell"
        assert system.model == "PowerEdge R740"
        assert system.serial_number == "SN123456"
        assert system.power_state == "On"

    def test_system_boot_section(self):
        data = {
            "@odata.id": "/redfish/v1/Systems/1",
            "Boot": {
                "BootSourceOverrideTarget": "Pxe",
                "BootSourceOverrideEnabled": "Once",
                "BootSourceOverrideMode": "UEFI",
                "BootSourceOverrideTarget@Redfish.AllowableValues": ["Pxe", "Hdd", "Cd"],
            }
        }
        system = System(**data)
        assert system.boot is not None
        assert system.boot.boot_source_override_target == "Pxe"
        assert "Hdd" in system.boot.allowable_values


class TestProcessor:
    def test_processor_fields(self):
        data = {
            "@odata.id": "/redfish/v1/Systems/1/Processors/CPU0",
            "Id": "CPU0",
            "Name": "Processor 0",
            "Model": "Intel(R) Xeon(R) Gold 6250",
            "Manufacturer": "Intel Corporation",
            "MaxSpeedMHz": 4200,
            "TotalCores": 8,
            "TotalThreads": 16,
            "Socket": "CPU0",
            "ProcessorType": "CPU",
        }
        cpu = Processor(**data)
        assert cpu.model == "Intel(R) Xeon(R) Gold 6250"
        assert cpu.total_cores == 8
        assert cpu.total_threads == 16


class TestMemory:
    def test_memory_fields(self):
        data = {
            "@odata.id": "/redfish/v1/Systems/1/Memory/DIMM0",
            "Id": "DIMM0",
            "Manufacturer": "Samsung",
            "CapacityMiB": 32768,
            "OperatingSpeedMhz": 3200,
            "MemoryDeviceType": "DDR4",
            "SerialNumber": "MEM123",
            "PartNumber": "M393A4K40CB2-CTD",
        }
        mem = Memory(**data)
        assert mem.manufacturer == "Samsung"
        assert mem.capacity_mib == 32768
        assert mem.operating_speed_mhz == 3200


class TestOem:
    def test_oem_with_public_key(self):
        """华为 xFusion / iBMC OEM format."""
        data = {
            "Public": {
                "ProductName": "2288H V5",
                "BMCVersion": "3.26.8.B260",
            }
        }
        oem = Oem.model_validate(data)
        assert oem.bmc is not None
        assert oem.bmc.product_name == "2288H V5"
        assert oem.bmc.bmc_version == "3.26.8.B260"

    def test_oem_with_bmc_key(self):
        """Alternative OEM key (some vendors use 'BMC')."""
        data = {
            "BMC": {
                "ProductName": "Server Model X",
            }
        }
        oem = Oem.model_validate(data)
        assert oem.bmc is not None
        assert oem.bmc.product_name == "Server Model X"

    def test_oem_with_lenovo_key(self):
        """Lenovo OEM format."""
        data = {
            "Lenovo": {
                "SystemBoardSerialNumber": "LEN123",
            }
        }
        oem = Oem.model_validate(data)
        assert oem.bmc is not None
        assert oem.bmc.system_board_serial_number == "LEN123"

    def test_oem_empty(self):
        oem = Oem.model_validate({})
        assert oem.bmc is None

    def test_oem_with_xfusion_speed_ratio(self):
        """超聚变风扇 OEM: Oem.xFusion.SpeedRatio."""
        data = {"xFusion": {"SpeedRatio": 80}}
        oem = Oem.model_validate(data)
        assert oem.bmc is not None
        assert oem.bmc.speed_ratio == 80

    def test_oem_with_public_speed_ratio(self):
        """H3C / ZTE / 浪潮新版风扇 OEM: Oem.Public.SpeedRatio."""
        data = {"Public": {"SpeedRatio": 65}}
        oem = Oem.model_validate(data)
        assert oem.bmc is not None
        assert oem.bmc.speed_ratio == 65

    def test_oem_with_goem_customestring_speed_ratio(self):
        """浪潮旧版风扇 OEM: Oem.gOemCustomeString.SpeedRatio (拼写来自 BMC 固件)."""
        data = {"gOemCustomeString": {"SpeedRatio": 70}}
        oem = Oem.model_validate(data)
        assert oem.bmc is not None
        assert oem.bmc.speed_ratio == 70

    def test_oem_merge_public_and_xfusion(self):
        """多 vendor key 合并：Public 优先，其他 vendor 补齐 Public 未提供的字段。"""
        data = {
            "Public": {"ProductName": "2288H V5"},
            "xFusion": {"SpeedRatio": 90},
        }
        oem = Oem.model_validate(data)
        assert oem.bmc is not None
        # Public 提供的字段保留
        assert oem.bmc.product_name == "2288H V5"
        # Public 未提供、由 xFusion 补齐的字段
        assert oem.bmc.speed_ratio == 90

    def test_oem_merge_public_wins_on_conflict(self):
        """当 Public 和其他 vendor 都提供同名字段时，Public 优先，不被覆盖。"""
        data = {
            "Public": {"SpeedRatio": 55},
            "xFusion": {"SpeedRatio": 99},
        }
        oem = Oem.model_validate(data)
        assert oem.bmc is not None
        # Public 已提供的字段不被后续 vendor 覆盖
        assert oem.bmc.speed_ratio == 55


class TestFanOem:
    """Fan.Oem 端到端解析：验证 Fan 顶层 oem 字段承接多厂商 SpeedRatio。"""

    def test_fan_with_xfusion_oem(self):
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Fans/0",
            "MemberId": "0",
            "Name": "Fan1",
            "Reading": 8000,
            "Oem": {"xFusion": {"SpeedRatio": 80}},
        }
        fan = Fan.model_validate(data)
        assert fan.name == "Fan1"
        assert fan.reading == 8000
        assert fan.oem is not None
        assert fan.oem.bmc is not None
        assert fan.oem.bmc.speed_ratio == 80

    def test_fan_with_goem_customestring_oem(self):
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Fans/1",
            "MemberId": "1",
            "Name": "Fan2",
            "Oem": {"gOemCustomeString": {"SpeedRatio": 70}},
        }
        fan = Fan.model_validate(data)
        assert fan.oem is not None
        assert fan.oem.bmc is not None
        assert fan.oem.bmc.speed_ratio == 70

    def test_fan_without_oem(self):
        """Fan 未提供 Oem 字段时应正常解析，oem 为 None。"""
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Fans/2",
            "MemberId": "2",
            "Name": "Fan3",
            "Reading": 6500,
        }
        fan = Fan.model_validate(data)
        assert fan.oem is None


class TestDriveOem:
    """
    Drive.Oem 端到端解析：验证多厂商 drive temperature / DriveID 的合并，
    以及宁畅特有的顶层 DiskTemperatureCelsius 便捷字段。
    """

    def test_drive_with_xfusion_oem(self):
        """超聚变: Oem.xFusion.TemperatureCelsius + Oem.xFusion.DriveID."""
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Drives/0",
            "Id": "0",
            "Name": "Drive0",
            "Oem": {"xFusion": {"TemperatureCelsius": "35", "DriveID": 3}},
        }
        drive = Drive.model_validate(data)
        assert drive.oem is not None
        assert drive.oem.bmc is not None
        assert drive.oem.bmc.drive_temperature_celsius == 35.0
        assert drive.oem.bmc.drive_id == 3

    def test_drive_with_public_lowercase_temperature(self):
        """联想 / 浪潮: Oem.Public.temperature (注意 JSON key 小写)."""
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Drives/1",
            "Id": "1",
            "Name": "Drive1",
            "Oem": {"Public": {"temperature": 33}},
        }
        drive = Drive.model_validate(data)
        assert drive.oem is not None
        assert drive.oem.bmc is not None
        assert drive.oem.bmc.drive_temperature == 33.0
        # 大写 alias 的 drive_temperature_celsius 不应被小写 key 污染
        assert drive.oem.bmc.drive_temperature_celsius is None

    def test_drive_with_public_temperature_celsius(self):
        """H3C / 中兴: Oem.Public.TemperatureCelsius (PascalCase)."""
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Drives/2",
            "Id": "2",
            "Name": "Drive2",
            "Oem": {"Public": {"TemperatureCelsius": "40"}},
        }
        drive = Drive.model_validate(data)
        assert drive.oem is not None
        assert drive.oem.bmc is not None
        assert drive.oem.bmc.drive_temperature_celsius == 40.0
        # 小写 alias 的 drive_temperature 不应被大写 key 污染
        assert drive.oem.bmc.drive_temperature is None

    def test_drive_with_suma_top_level_disk_temperature(self):
        """宁畅: 顶层 Drive.DiskTemperatureCelsius (不在 Oem 下)."""
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Drives/3",
            "Id": "3",
            "Name": "Drive3",
            "DiskTemperatureCelsius": 29,
        }
        drive = Drive.model_validate(data)
        assert drive.disk_temperature_celsius == 29.0
        # Suma 场景没有 Oem, oem 字段应为 None
        assert drive.oem is None

    def test_drive_oem_merge_public_and_xfusion(self):
        """多 vendor 合并：Public.temperature (联想风格) 与 xFusion.DriveID 共存。"""
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Drives/4",
            "Id": "4",
            "Name": "Drive4",
            "Oem": {
                "Public": {"temperature": 30},
                "xFusion": {"DriveID": 7},
            },
        }
        drive = Drive.model_validate(data)
        assert drive.oem is not None
        assert drive.oem.bmc is not None
        assert drive.oem.bmc.drive_temperature == 30.0
        assert drive.oem.bmc.drive_id == 7

    def test_drive_without_oem_and_without_disk_temperature(self):
        """未提供任何 OEM/温度字段时应正常解析。"""
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Drives/5",
            "Id": "5",
            "Name": "Drive5",
            "CapacityBytes": 1024 * 1024 * 1024,
        }
        drive = Drive.model_validate(data)
        assert drive.oem is None
        assert drive.disk_temperature_celsius is None
        assert drive.capacity_bytes == 1024 * 1024 * 1024


class TestPower:
    def test_power_supply_fields(self):
        data = {
            "@odata.id": "/redfish/v1/Chassis/1/Power",
            "PowerSupplies": [
                {
                    "MemberId": "0",
                    "Name": "Power Supply 1",
                    "Manufacturer": "Delta",
                    "Model": "DPS-800AB-22 A",
                    "SerialNumber": "PSU123",
                    "PowerCapacityWatts": 800,
                    "PowerInputWatts": 700,
                    "PowerOutputWatts": 650,
                    "Status": {"State": "Enabled", "Health": "OK"},
                }
            ],
        }
        power = Power(**data)
        assert len(power.power_supplies) == 1
        psu = power.power_supplies[0]
        assert psu.manufacturer == "Delta"
        assert psu.power_capacity_watts == 800


class TestCollection:
    def test_collection_generic(self):
        col = Collection.model_construct(
            odata_id="/redfish/v1/Systems",
            members=[
                System.model_construct(odata_id="/redfish/v1/Systems/1", id="1"),
            ],
            members_count=1,
        )
        assert len(col.members) == 1
        assert col.members[0].id == "1"


class TestAccount:
    def test_account_fields(self):
        data = {
            "@odata.id": "/redfish/v1/AccountService/Accounts/Admin",
            "Id": "Admin",
            "UserName": "Admin",
            "RoleId": "Administrator",
            "Enabled": True,
            "Locked": False,
        }
        account = Account(**data)
        assert account.user_name == "Admin"
        assert account.role_id == "Administrator"
        assert account.enabled is True


class TestSession:
    def test_session_fields(self):
        data = {
            "@odata.id": "/redfish/v1/SessionService/Sessions/1",
            "Id": "1",
            "UserName": "Admin",
            "SessionType": "Redfish",
        }
        session = Session(**data)
        assert session.user_name == "Admin"
        assert session.x_auth_token is None  # Set separately from header


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
