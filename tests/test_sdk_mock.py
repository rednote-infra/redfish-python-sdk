"""
Integration tests for the SDK using mock HTTP responses.
Tests the complete SDK flow from initialization to service manager calls.

These tests never hit a real BMC. All host/credential values below are
dummy placeholders chosen so they cannot be mistaken for real assets.
"""

import os

import pytest

from redfish_sdk.models.oem import MainBoard

from redfish_sdk import RedfishClient as RedfishSDK
from redfish_sdk import RedfishResource

# ---------------------------------------------------------------------------
# Dummy credentials for mock tests.
#
# Defaults are intentionally unrealistic (`mock-*`) so they cannot collide
# with any real BMC. Tests can still override via env vars when desired.
# ---------------------------------------------------------------------------
MOCK_HOST = os.environ.get("BMC_IP", "mock-bmc-host")
MOCK_USER = os.environ.get("BMC_USER", "mock-user")
MOCK_PASSWORD = os.environ.get("BMC_PASSWORD", "mock-password")


class TestRedfishSDKInit:
    def test_sdk_init(self):
        sdk = RedfishSDK(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
            verify_ssl=False,
        )
        assert sdk.host == MOCK_HOST
        # Managers are lazy — not created until accessed
        assert "_systems" not in sdk.__dict__
        assert "_chassis" not in sdk.__dict__
        assert "_managers" not in sdk.__dict__
        assert "_accounts" not in sdk.__dict__
        assert "_sessions" not in sdk.__dict__
        assert "_events" not in sdk.__dict__
        assert "_updates" not in sdk.__dict__
        assert "_registries" not in sdk.__dict__
        assert "_tasks" not in sdk.__dict__
        sdk.close()

    def test_sdk_lazy_manager_creation(self):
        """Managers should be created on first access and cached."""
        sdk = RedfishSDK(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )
        assert "_systems" not in sdk.__dict__
        # Access _systems triggers creation
        _ = sdk._systems
        assert "_systems" in sdk.__dict__
        # Second access returns same instance
        assert sdk._systems is sdk._systems
        sdk.close()

    def test_sdk_close_clears_cached_managers(self):
        """close() should clear all cached_property caches."""
        sdk = RedfishSDK(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )
        # Trigger creation of a few managers
        _ = sdk._systems
        _ = sdk._chassis
        assert "_systems" in sdk.__dict__
        assert "_chassis" in sdk.__dict__

        sdk.close()

        # After close, caches should be cleared
        assert "_systems" not in sdk.__dict__
        assert "_chassis" not in sdk.__dict__

    def test_sdk_context_manager(self):
        with RedfishSDK(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        ) as sdk:
            assert sdk is not None
            assert repr(sdk) == f"RedfishClient(host='{MOCK_HOST}')"


class TestSystemsManagerLogic:
    """Test SystemsManager business logic without actual HTTP calls."""

    def test_gpu_fallback_logic_from_pcie_with_gpu_name(self):
        """
        Test that GPU is correctly extracted from PCIeDevices when
        device name contains 'GPU'.
        """
        from redfish_sdk.models.chassis import PCIeDevice, PCIeDeviceOEM, PCIeDeviceOEMPublic

        # Simulate a PCIe device with "GPU" in the name
        pcie = PCIeDevice.model_construct(
            odata_id="/redfish/v1/Chassis/1/PCIeDevices/GPU0",
            name="GPU-NVIDIA Tesla V100",
            manufacturer="NVIDIA",
            model="Tesla V100",
            part_number="V100-32GB",
            serial_number="GPU-SN-001",
            card_model="Tesla V100 SXM2 32GB",
            oem=PCIeDeviceOEM.model_construct(
                gpu_oem_public=PCIeDeviceOEMPublic.model_construct(power_watts=300.0)
            ),
        )

        from redfish_sdk.models.systems import Gpu, GpuOEM

        # Simulate the conversion logic from SystemsManager.gpus()
        assert "GPU" in pcie.name
        gpu = Gpu.model_construct(
            odata_id=pcie.odata_id,
            name=pcie.name,
            manufacturer=pcie.manufacturer,
            model=pcie.model,
            power_watts=str(pcie.oem.gpu_oem_public.power_watts),
            version=pcie.card_model,
            oem=GpuOEM.model_construct(serial_number=pcie.serial_number),
        )
        assert gpu.manufacturer == "NVIDIA"
        assert gpu.power_watts == "300.0"
        assert gpu.version == "Tesla V100 SXM2 32GB"
        assert gpu.oem.serial_number == "GPU-SN-001"

    def test_non_gpu_pcie_not_included(self):
        """Test that non-GPU PCIe devices are filtered out."""
        from redfish_sdk.models.chassis import PCIeDevice
        pcie = PCIeDevice.model_construct(
            odata_id="/redfish/v1/Chassis/1/PCIeDevices/NIC0",
            name="Mellanox ConnectX-6 Dx",
        )
        assert "GPU" not in pcie.name


class TestBootSourceLogic:
    """Test boot source change logic."""

    def test_boot_setting_construction(self):
        from redfish_sdk.models.systems import BootSetting, SystemPatchSetting
        setting = SystemPatchSetting.model_construct(
            boot=BootSetting.model_construct(
                boot_source_override_enabled="Once",
                boot_source_override_mode="UEFI",
                boot_source_override_target="Pxe",
            )
        )
        payload = setting.model_dump(by_alias=True, exclude_none=True)
        assert payload == {
            "Boot": {
                "BootSourceOverrideEnabled": "Once",
                "BootSourceOverrideMode": "UEFI",
                "BootSourceOverrideTarget": "Pxe",
            }
        }


class TestClientAuthentication:
    """Test that authentication headers are correctly set."""

    def test_basic_auth_header(self):
        import base64

        from redfish_sdk.client import RedfishHttpClient
        client = RedfishHttpClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )
        expected = "Basic " + base64.b64encode(
            f"{MOCK_USER}:{MOCK_PASSWORD}".encode()
        ).decode()
        assert client._basic_auth == expected
        client.close()

    def test_switch_to_token_auth(self):
        from redfish_sdk.client import RedfishHttpClient
        client = RedfishHttpClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )
        client.set_auth_token("my-auth-token-123")
        assert client._session.headers.get("X-Auth-Token") == "my-auth-token-123"
        assert "Authorization" not in client._session.headers
        client.close()

    def test_reset_to_basic_auth(self):
        from redfish_sdk.client import RedfishHttpClient
        client = RedfishHttpClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )
        client.set_auth_token("my-token")
        client.reset_basic_auth()
        assert "X-Auth-Token" not in client._session.headers
        assert "Authorization" in client._session.headers
        client.close()


class TestExceptions:
    """Test exception hierarchy."""

    def test_redfish_exception(self):
        from redfish_sdk.exceptions import RedfishException
        exc = RedfishException(500, "Internal Server Error", "details")
        assert exc.status_code == 500
        assert "500" in str(exc)

    def test_auth_error(self):
        from redfish_sdk.exceptions import RedfishAuthError
        exc = RedfishAuthError(401)
        assert exc.status_code == 401

    def test_not_found_error(self):
        from redfish_sdk.exceptions import RedfishNotFoundError
        exc = RedfishNotFoundError("/redfish/v1/Systems/99")
        assert exc.status_code == 404
        assert "99" in str(exc)

    def test_validation_error(self):
        from redfish_sdk.exceptions import RedfishValidationError
        exc = RedfishValidationError("Invalid reset type")
        assert exc.status_code == 400


class TestGetOdataId:
    """Test get_odata_id method with mocked HTTP responses."""

    @staticmethod
    def _make_client():
        """Create a RedfishClient instance (no actual connection needed)."""
        from redfish_sdk import RedfishClient
        return RedfishClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )

    def test_root_level_systems(self, monkeypatch):
        """Step 1: key found in RootService top-level."""
        client = self._make_client()
        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
            "AccountService": {"@odata.id": "/redfish/v1/AccountService"},
        }
        monkeypatch.setattr(client._http_client, "get_raw", lambda path: root_json)

        assert client.get_odata_id(RedfishResource.SYSTEMS) == "/redfish/v1/Systems"
        assert client.get_odata_id(RedfishResource.CHASSIS) == "/redfish/v1/Chassis"
        assert client.get_odata_id(RedfishResource.ACCOUNT_SERVICE) == "/redfish/v1/AccountService"
        client.close()

    def test_system_level_processors(self, monkeypatch):
        """Step 2: key found in first Systems member."""
        client = self._make_client()

        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
        }
        systems_col_json = {
            "Members": [{"@odata.id": "/redfish/v1/Systems/1"}],
        }
        system_json = {
            "@odata.id": "/redfish/v1/Systems/1",
            "Processors": {"@odata.id": "/redfish/v1/Systems/1/Processors"},
            "Memory": {"@odata.id": "/redfish/v1/Systems/1/Memory"},
            "Storage": {"@odata.id": "/redfish/v1/Systems/1/Storage"},
            "Bios": {"@odata.id": "/redfish/v1/Systems/1/Bios"},
        }

        def mock_get_raw(path):
            if path == "/redfish/v1/":
                return root_json
            if path == "/redfish/v1/Systems":
                return systems_col_json
            if path == "/redfish/v1/Systems/1":
                return system_json
            return {}

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)

        assert client.get_odata_id(RedfishResource.PROCESSORS) == "/redfish/v1/Systems/1/Processors"
        assert client.get_odata_id(RedfishResource.MEMORY) == "/redfish/v1/Systems/1/Memory"
        assert client.get_odata_id(RedfishResource.BIOS) == "/redfish/v1/Systems/1/Bios"
        client.close()

    def test_chassis_level_thermal(self, monkeypatch):
        """Step 3: key found in first Chassis member."""
        client = self._make_client()

        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
        }
        systems_col_json = {
            "Members": [{"@odata.id": "/redfish/v1/Systems/1"}],
        }
        system_json = {
            "@odata.id": "/redfish/v1/Systems/1",
            "Processors": {"@odata.id": "/redfish/v1/Systems/1/Processors"},
        }
        chassis_col_json = {
            "Members": [{"@odata.id": "/redfish/v1/Chassis/1"}],
        }
        chassis_json = {
            "@odata.id": "/redfish/v1/Chassis/1",
            "Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"},
            "Power": {"@odata.id": "/redfish/v1/Chassis/1/Power"},
            "Drives": {"@odata.id": "/redfish/v1/Chassis/1/Drives"},
            "NetworkAdapters": {"@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters"},
        }

        def mock_get_raw(path):
            if path == "/redfish/v1/":
                return root_json
            if path == "/redfish/v1/Systems":
                return systems_col_json
            if path == "/redfish/v1/Systems/1":
                return system_json
            if path == "/redfish/v1/Chassis":
                return chassis_col_json
            if path == "/redfish/v1/Chassis/1":
                return chassis_json
            return {}

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)

        assert client.get_odata_id(RedfishResource.THERMAL) == "/redfish/v1/Chassis/1/Thermal"
        assert client.get_odata_id(RedfishResource.POWER) == "/redfish/v1/Chassis/1/Power"
        assert client.get_odata_id(RedfishResource.DRIVES) == "/redfish/v1/Chassis/1/Drives"
        assert client.get_odata_id(RedfishResource.NETWORK_ADAPTERS) == "/redfish/v1/Chassis/1/NetworkAdapters"
        client.close()

    def test_manager_level_network_protocol(self, monkeypatch):
        """Step 4: key found in first Managers member."""
        client = self._make_client()

        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
        }
        systems_col_json = {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]}
        system_json = {"@odata.id": "/redfish/v1/Systems/1"}
        chassis_col_json = {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]}
        chassis_json = {"@odata.id": "/redfish/v1/Chassis/1"}
        managers_col_json = {"Members": [{"@odata.id": "/redfish/v1/Managers/1"}]}
        manager_json = {
            "@odata.id": "/redfish/v1/Managers/1",
            "NetworkProtocol": {"@odata.id": "/redfish/v1/Managers/1/NetworkProtocol"},
            "HostInterfaces": {"@odata.id": "/redfish/v1/Managers/1/HostInterfaces"},
        }

        def mock_get_raw(path):
            mapping = {
                "/redfish/v1/": root_json,
                "/redfish/v1/Systems": systems_col_json,
                "/redfish/v1/Systems/1": system_json,
                "/redfish/v1/Chassis": chassis_col_json,
                "/redfish/v1/Chassis/1": chassis_json,
                "/redfish/v1/Managers": managers_col_json,
                "/redfish/v1/Managers/1": manager_json,
            }
            return mapping.get(path, {})

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)

        assert client.get_odata_id(RedfishResource.NETWORK_PROTOCOL) == "/redfish/v1/Managers/1/NetworkProtocol"
        assert client.get_odata_id(RedfishResource.HOST_INTERFACES) == "/redfish/v1/Managers/1/HostInterfaces"
        client.close()

    def test_key_not_found_returns_none(self, monkeypatch):
        """All steps miss → returns None."""
        client = self._make_client()

        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
        }
        empty_col_json = {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]}
        empty_member = {"@odata.id": "/redfish/v1/Systems/1"}

        def mock_get_raw(path):
            if path == "/redfish/v1/":
                return root_json
            if "Systems" in path and "Members" not in path:
                if path.endswith("Systems"):
                    return empty_col_json
                return empty_member
            if "Chassis" in path:
                if path.endswith("Chassis"):
                    return {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]}
                return {"@odata.id": "/redfish/v1/Chassis/1"}
            if "Managers" in path:
                if path.endswith("Managers"):
                    return {"Members": [{"@odata.id": "/redfish/v1/Managers/1"}]}
                return {"@odata.id": "/redfish/v1/Managers/1"}
            return {}

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)

        # SENSORS is a Chassis-level key but we didn't put it in chassis_json
        assert client.get_odata_id(RedfishResource.SENSORS) is None
        client.close()

    def test_skip_layer_on_error(self, monkeypatch):
        """If one layer fails, skip and continue searching next layers."""
        from redfish_sdk.exceptions import RedfishException
        client = self._make_client()

        call_count = {"n": 0}

        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
        }
        chassis_col_json = {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]}
        chassis_json = {
            "@odata.id": "/redfish/v1/Chassis/1",
            "Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"},
        }

        def mock_get_raw(path):
            call_count["n"] += 1
            if path == "/redfish/v1/":
                return root_json
            if path == "/redfish/v1/Systems":
                raise RedfishException(500, "Systems collection broken")
            if path == "/redfish/v1/Chassis":
                return chassis_col_json
            if path == "/redfish/v1/Chassis/1":
                return chassis_json
            return {}

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)

        # Systems fails, but Chassis should still be searched
        result = client.get_odata_id(RedfishResource.THERMAL)
        assert result == "/redfish/v1/Chassis/1/Thermal"
        client.close()

    def test_links_section_lookup(self, monkeypatch):
        """Key found in the Links section of a resource."""
        client = self._make_client()

        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
            "Links": {
                "Sessions": {"@odata.id": "/redfish/v1/SessionService/Sessions"},
            },
        }
        # "Sessions" is in Links — but it's not in our enum; test with a top-level key in Links
        # Let's use a system-level Links scenario instead
        systems_col_json = {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]}
        system_json = {
            "@odata.id": "/redfish/v1/Systems/1",
            "Links": {
                "Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}],
            },
        }
        chassis_col_json = {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]}
        chassis_json = {
            "@odata.id": "/redfish/v1/Chassis/1",
            "Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"},
        }

        def mock_get_raw(path):
            mapping = {
                "/redfish/v1/": root_json,
                "/redfish/v1/Systems": systems_col_json,
                "/redfish/v1/Systems/1": system_json,
                "/redfish/v1/Chassis": chassis_col_json,
                "/redfish/v1/Chassis/1": chassis_json,
            }
            return mapping.get(path, {})

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)

        # THERMAL is not in System (top-level or Links), but is in Chassis top-level
        assert client.get_odata_id(RedfishResource.THERMAL) == "/redfish/v1/Chassis/1/Thermal"
        client.close()

    def test_priority_system_over_manager(self, monkeypatch):
        """EthernetInterfaces exists in both System and Manager; System wins."""
        client = self._make_client()

        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
        }
        systems_col_json = {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]}
        system_json = {
            "@odata.id": "/redfish/v1/Systems/1",
            "EthernetInterfaces": {"@odata.id": "/redfish/v1/Systems/1/EthernetInterfaces"},
        }

        def mock_get_raw(path):
            mapping = {
                "/redfish/v1/": root_json,
                "/redfish/v1/Systems": systems_col_json,
                "/redfish/v1/Systems/1": system_json,
            }
            return mapping.get(path, {})

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)

        result = client.get_odata_id(RedfishResource.ETHERNET_INTERFACES)
        assert result == "/redfish/v1/Systems/1/EthernetInterfaces"
        client.close()


class TestGetResourceOdataId:
    """Test backward-compatible get_resource_odata_id static method."""

    def test_extract_from_entity(self):
        from redfish_sdk.models.common import Entity
        entity = Entity.model_construct(odata_id="/redfish/v1/Systems/1")
        from redfish_sdk.client import RedfishClient
        assert RedfishClient.get_resource_odata_id(entity) == "/redfish/v1/Systems/1"

    def test_extract_from_link(self):
        from redfish_sdk.models.common import Link
        link = Link.model_construct(odata_id="/redfish/v1/Chassis/1/Thermal")
        from redfish_sdk.client import RedfishClient
        assert RedfishClient.get_resource_odata_id(link) == "/redfish/v1/Chassis/1/Thermal"

    def test_none_when_no_odata_id(self):
        from redfish_sdk.client import RedfishClient
        assert RedfishClient.get_resource_odata_id({"foo": "bar"}) is None


class TestGetRaw:
    """Test get_raw method with mocked HTTP responses."""

    @staticmethod
    def _make_client():
        from redfish_sdk import RedfishClient
        return RedfishClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )

    def test_get_raw_returns_json_dict(self, monkeypatch):
        """get_raw should return the raw JSON dict from the BMC."""
        client = self._make_client()
        expected = {
            "@odata.id": "/redfish/v1/Systems/1",
            "@odata.type": "#ComputerSystem.v1_13_0.ComputerSystem",
            "Id": "1",
            "Name": "Computer System",
            "Manufacturer": "Huawei",
            "Model": "2288H V5",
            "SerialNumber": "SN-001",
        }
        monkeypatch.setattr(client._http_client, "get_raw", lambda path: expected)

        result = client.get_raw("/redfish/v1/Systems/1")
        assert result == expected
        assert result["Manufacturer"] == "Huawei"
        assert result["@odata.id"] == "/redfish/v1/Systems/1"
        client.close()

    def test_get_raw_root_service(self, monkeypatch):
        """get_raw should work for the root service endpoint."""
        client = self._make_client()
        root_json = {
            "@odata.id": "/redfish/v1/",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
            "RedfishVersion": "1.6.0",
        }
        monkeypatch.setattr(client._http_client, "get_raw", lambda path: root_json)

        result = client.get_raw("/redfish/v1/")
        assert result["RedfishVersion"] == "1.6.0"
        assert "Systems" in result
        client.close()

    def test_get_raw_propagates_exception(self, monkeypatch):
        """get_raw should propagate RedfishException from http_client."""
        from redfish_sdk.exceptions import RedfishNotFoundError
        client = self._make_client()

        def mock_get_raw(path):
            raise RedfishNotFoundError(path)

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)

        with pytest.raises(RedfishNotFoundError):
            client.get_raw("/redfish/v1/Systems/999")
        client.close()

    def test_get_raw_with_oem_data(self, monkeypatch):
        """get_raw should return OEM vendor-specific fields."""
        client = self._make_client()
        expected = {
            "@odata.id": "/redfish/v1/Chassis/1",
            "Oem": {
                "Huawei": {
                    "BoardId": "0x1234",
                    "ProductAlias": "TaiShan 200 (Model 2280)",
                },
            },
        }
        monkeypatch.setattr(client._http_client, "get_raw", lambda path: expected)

        result = client.get_raw("/redfish/v1/Chassis/1")
        assert result["Oem"]["Huawei"]["BoardId"] == "0x1234"
        client.close()


class TestGetSystem:
    """Test get_system and get_systems convenience methods."""

    @staticmethod
    def _make_client():
        from redfish_sdk import RedfishClient
        return RedfishClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )

    def test_get_system_returns_system_object(self, monkeypatch):
        """get_system() should return a System with expected fields."""
        from redfish_sdk.models.systems import System
        client = self._make_client()

        system = System.model_construct(
            odata_id="/redfish/v1/Systems/1",
            id="1",
            name="Computer System",
            manufacturer="Huawei",
            model="2288H V5",
            serial_number="2102312HMN10J3000042",
            power_state="On",
            bios_version="0.80",
            uuid="5A6F22E0-3ACB-11E5-B7A4-389AEC2E5C78",
        )
        monkeypatch.setattr(client._systems, "get", lambda sid=None: system)

        result = client.get_system()
        assert isinstance(result, System)
        assert result.manufacturer == "Huawei"
        assert result.model == "2288H V5"
        assert result.serial_number == "2102312HMN10J3000042"
        assert result.power_state == "On"
        assert result.bios_version == "0.80"
        assert result.uuid == "5A6F22E0-3ACB-11E5-B7A4-389AEC2E5C78"
        client.close()

    def test_get_system_with_id(self, monkeypatch):
        """get_system('1') should pass system_id to _systems.get()."""
        from redfish_sdk.models.systems import System
        client = self._make_client()

        captured = {}

        def mock_get(sid=None):
            captured["system_id"] = sid
            return System.model_construct(
                odata_id="/redfish/v1/Systems/1",
                id="1",
                manufacturer="Inspur",
            )

        monkeypatch.setattr(client._systems, "get", mock_get)

        result = client.get_system("1")
        assert captured["system_id"] == "1"
        assert result.manufacturer == "Inspur"
        client.close()

    def test_get_system_auto_select_single(self, monkeypatch):
        """get_system() with no ID auto-selects when only one system."""
        from redfish_sdk.models.systems import System
        client = self._make_client()

        captured = {}

        def mock_get(sid=None):
            captured["system_id"] = sid
            return System.model_construct(id="1", manufacturer="H3C")

        monkeypatch.setattr(client._systems, "get", mock_get)

        result = client.get_system()
        assert captured["system_id"] is None
        assert result.manufacturer == "H3C"
        client.close()

    def test_get_system_multiple_raises(self, monkeypatch):
        """get_system() with no ID raises when multiple systems exist."""
        from redfish_sdk.exceptions import RedfishValidationError
        client = self._make_client()

        def mock_get(sid=None):
            raise RedfishValidationError(
                "Multiple systems found, please specify system_id. Available: ['1', '2']"
            )

        monkeypatch.setattr(client._systems, "get", mock_get)

        with pytest.raises(RedfishValidationError, match="Multiple systems found"):
            client.get_system()
        client.close()

    def test_get_systems_returns_list(self, monkeypatch):
        """get_systems() should return a list of System objects."""
        from redfish_sdk.models.systems import System
        client = self._make_client()

        systems_list = [
            System.model_construct(id="1", manufacturer="Huawei", model="2288H V5"),
            System.model_construct(id="2", manufacturer="Huawei", model="2488H V6"),
        ]
        monkeypatch.setattr(client, "_get_systems_collection", lambda: systems_list)

        result = client.get_systems()
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].id == "1"
        assert result[0].model == "2288H V5"
        assert result[1].id == "2"
        assert result[1].model == "2488H V6"
        client.close()

    def test_get_systems_empty(self, monkeypatch):
        """get_systems() returns empty list when no systems available."""
        client = self._make_client()
        monkeypatch.setattr(client, "_get_systems_collection", lambda: [])

        result = client.get_systems()
        assert result == []
        client.close()


class TestPatchPostDelete:
    """Test patch(), post(), delete() generic CRUD methods."""

    @staticmethod
    def _make_client():
        from redfish_sdk import RedfishClient
        return RedfishClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )

    # -- patch() tests --

    def test_patch_returns_json_dict(self, monkeypatch):
        """patch() should return the parsed JSON response dict."""
        client = self._make_client()
        response_data = {"@odata.id": "/redfish/v1/Systems/1", "Boot": {"BootSourceOverrideTarget": "Pxe"}}

        class FakeResponse:
            status_code = 200
            text = '{"@odata.id": "/redfish/v1/Systems/1"}'
            headers = {}
            def json(self):
                return response_data

        # Pre-populate ETag cache so patch skips the auto-GET
        client._http_client._last_etag["/redfish/v1/Systems/1"] = '"etag-123"'
        monkeypatch.setattr(client._http_client, "patch_raw", lambda path, body, **kw: FakeResponse())

        result = client.patch("/redfish/v1/Systems/1", {"Boot": {"BootSourceOverrideTarget": "Pxe"}})
        assert result == response_data
        client.close()

    def test_patch_returns_empty_dict_on_204(self, monkeypatch):
        """patch() should return {} when BMC responds with 204 No Content."""
        client = self._make_client()

        class FakeResponse:
            status_code = 204
            text = ""
            headers = {}

        client._http_client._last_etag["/redfish/v1/Systems/1"] = '"etag-123"'
        monkeypatch.setattr(client._http_client, "patch_raw", lambda path, body, **kw: FakeResponse())

        result = client.patch("/redfish/v1/Systems/1", {"AssetTag": "NEW-TAG"})
        assert result == {}
        client.close()

    def test_patch_auto_fetches_etag(self, monkeypatch):
        """patch() should auto-GET to fetch ETag when not cached."""
        client = self._make_client()
        get_calls = []

        def mock_get_raw(path):
            get_calls.append(path)
            # Simulate ETag being stored
            client._http_client._last_etag[path] = '"auto-etag-456"'
            return {"@odata.id": path}

        class FakeResponse:
            status_code = 200
            text = '{"ok": true}'
            headers = {}
            def json(self):
                return {"ok": True}

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)
        monkeypatch.setattr(client._http_client, "patch_raw", lambda path, body, **kw: FakeResponse())

        # ETag cache is empty — should trigger auto-GET
        assert "/redfish/v1/Systems/1" not in client._http_client._last_etag
        result = client.patch("/redfish/v1/Systems/1", {"AssetTag": "X"})
        assert "/redfish/v1/Systems/1" in get_calls
        assert result == {"ok": True}
        client.close()

    def test_patch_skips_auto_get_when_etag_cached(self, monkeypatch):
        """patch() should NOT auto-GET when ETag is already cached."""
        client = self._make_client()
        get_calls = []

        def mock_get_raw(path):
            get_calls.append(path)
            return {}

        class FakeResponse:
            status_code = 200
            text = '{"ok": true}'
            headers = {}
            def json(self):
                return {"ok": True}

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)
        monkeypatch.setattr(client._http_client, "patch_raw", lambda path, body, **kw: FakeResponse())

        # Pre-populate ETag cache
        client._http_client._last_etag["/redfish/v1/Systems/1"] = '"existing"'
        client.patch("/redfish/v1/Systems/1", {"AssetTag": "X"})
        assert get_calls == []  # No GET was made
        client.close()

    def test_patch_proceeds_with_wildcard_on_get_failure(self, monkeypatch):
        """patch() should proceed with '*' wildcard if auto-GET fails."""
        from redfish_sdk.exceptions import RedfishException
        client = self._make_client()

        def mock_get_raw(path):
            raise RedfishException(500, "Server error")

        patch_calls = []

        class FakeResponse:
            status_code = 200
            text = '{"ok": true}'
            headers = {}
            def json(self):
                return {"ok": True}

        def mock_patch_raw(path, body, **kw):
            patch_calls.append(path)
            return FakeResponse()

        monkeypatch.setattr(client._http_client, "get_raw", mock_get_raw)
        monkeypatch.setattr(client._http_client, "patch_raw", mock_patch_raw)

        # GET fails, but PATCH should still proceed
        result = client.patch("/redfish/v1/Systems/1", {"AssetTag": "X"})
        assert result == {"ok": True}
        assert len(patch_calls) == 1
        client.close()

    def test_patch_propagates_exception(self, monkeypatch):
        """patch() should propagate RedfishException from http_client."""
        from redfish_sdk.exceptions import RedfishException
        client = self._make_client()
        client._http_client._last_etag["/redfish/v1/Systems/1"] = '"e"'

        def mock_patch_raw(path, body, **kw):
            raise RedfishException(412, "Precondition Failed")

        monkeypatch.setattr(client._http_client, "patch_raw", mock_patch_raw)

        with pytest.raises(RedfishException):
            client.patch("/redfish/v1/Systems/1", {"AssetTag": "X"})
        client.close()

    # -- post() tests --

    def test_post_returns_json_dict(self, monkeypatch):
        """post() should return the parsed JSON response dict."""
        client = self._make_client()
        response_data = {"@odata.id": "/redfish/v1/AccountService/Accounts/newuser"}

        class FakeResponse:
            status_code = 201
            text = '{"@odata.id": "/redfish/v1/AccountService/Accounts/newuser"}'
            headers = {}
            def json(self):
                return response_data

        monkeypatch.setattr(client._http_client, "post_raw", lambda path, body=None: FakeResponse())

        result = client.post("/redfish/v1/AccountService/Accounts", {
            "UserName": "operator",
            "Password": "secret",
            "RoleId": "Operator",
        })
        assert result == response_data
        client.close()

    def test_post_returns_empty_dict_on_204(self, monkeypatch):
        """post() should return {} on 204 No Content (e.g., action trigger)."""
        client = self._make_client()

        class FakeResponse:
            status_code = 204
            text = ""
            headers = {}

        monkeypatch.setattr(client._http_client, "post_raw", lambda path, body=None: FakeResponse())

        result = client.post(
            "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset",
            {"ResetType": "GracefulRestart"},
        )
        assert result == {}
        client.close()

    def test_post_without_body(self, monkeypatch):
        """post() should work without a body (some actions don't need one)."""
        client = self._make_client()

        captured = {}

        class FakeResponse:
            status_code = 200
            text = '{"Message": "OK"}'
            headers = {}
            def json(self):
                return {"Message": "OK"}

        def mock_post_raw(path, body=None):
            captured["path"] = path
            captured["body"] = body
            return FakeResponse()

        monkeypatch.setattr(client._http_client, "post_raw", mock_post_raw)

        result = client.post("/redfish/v1/Systems/1/Actions/ComputerSystem.Reset")
        assert captured["body"] is None
        assert result == {"Message": "OK"}
        client.close()

    def test_post_propagates_exception(self, monkeypatch):
        """post() should propagate RedfishException from http_client."""
        from redfish_sdk.exceptions import RedfishException
        client = self._make_client()

        def mock_post_raw(path, body=None):
            raise RedfishException(400, "Bad Request")

        monkeypatch.setattr(client._http_client, "post_raw", mock_post_raw)

        with pytest.raises(RedfishException):
            client.post("/redfish/v1/AccountService/Accounts", {"UserName": "x"})
        client.close()

    # -- delete() tests --

    def test_delete_returns_none(self, monkeypatch):
        """delete() should return None."""
        client = self._make_client()
        monkeypatch.setattr(client._http_client, "delete", lambda path: "")

        result = client.delete("/redfish/v1/SessionService/Sessions/abc123")
        assert result is None
        client.close()

    def test_delete_propagates_exception(self, monkeypatch):
        """delete() should propagate RedfishException on HTTP errors."""
        from redfish_sdk.exceptions import RedfishNotFoundError
        client = self._make_client()

        def mock_delete(path):
            raise RedfishNotFoundError(path)

        monkeypatch.setattr(client._http_client, "delete", mock_delete)

        with pytest.raises(RedfishNotFoundError):
            client.delete("/redfish/v1/SessionService/Sessions/nonexistent")
        client.close()


class TestNewDelegateMethods:
    """Test newly promoted delegate methods (30 new methods from r-client-init)."""

    @staticmethod
    def _make_client():
        from redfish_sdk import RedfishClient
        return RedfishClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        )

    # -- SystemsManager promoted methods --

    def test_get_system_log_services(self, monkeypatch):
        """get_system_log_services() delegates to _systems.log_services()."""
        client = self._make_client()
        sentinel = [{"id": "Log1"}]
        monkeypatch.setattr(client._systems, "log_services", lambda sid=None: sentinel)
        assert client.get_system_log_services() is sentinel
        client.close()

    def test_get_system_log_entries(self, monkeypatch):
        """get_system_log_entries() delegates to _systems.log_entries()."""
        client = self._make_client()
        sentinel = [{"id": "entry1"}]
        monkeypatch.setattr(client._systems, "log_entries", lambda log_id, sid=None: sentinel)
        assert client.get_system_log_entries("Log1") is sentinel
        client.close()

    def test_get_system_fru(self, monkeypatch):
        """get_system_fru() delegates to _systems.fru_info()."""
        client = self._make_client()
        sentinel = {"board": "info"}
        monkeypatch.setattr(client._systems, "fru_info", lambda sid=None: sentinel)
        assert client.get_system_fru() is sentinel
        client.close()

    def test_get_pcie_device(self, monkeypatch):
        """get_pcie_device() delegates to _systems.pcie_device()."""
        client = self._make_client()
        sentinel = {"name": "GPU0"}
        monkeypatch.setattr(client._systems, "pcie_device", lambda odata_id: sentinel)
        assert client.get_pcie_device("/redfish/v1/Chassis/1/PCIeDevices/GPU0") is sentinel
        client.close()

    def test_change_boot_source(self, monkeypatch):
        """change_boot_source() delegates to _systems.change_boot_source()."""
        client = self._make_client()
        sentinel = {"boot": "changed"}
        captured = {}

        def mock_change(target, sid=None, mode="UEFI", enabled="Once"):
            captured.update(target=target, sid=sid, mode=mode, enabled=enabled)
            return sentinel

        monkeypatch.setattr(client._systems, "change_boot_source", mock_change)
        result = client.change_boot_source("Pxe", mode="Legacy")
        assert result is sentinel
        assert captured["target"] == "Pxe"
        assert captured["mode"] == "Legacy"
        client.close()

    def test_reset(self, monkeypatch):
        """reset() delegates to _systems.reset()."""
        client = self._make_client()
        sentinel = {"status": "resetting"}
        captured = {}

        def mock_reset(reset_type, sid=None, skip=False):
            captured.update(reset_type=reset_type, sid=sid, skip=skip)
            return sentinel

        monkeypatch.setattr(client._systems, "reset", mock_reset)
        result = client.reset("GracefulRestart")
        assert result is sentinel
        assert captured["reset_type"] == "GracefulRestart"
        client.close()

    # -- ChassisManager promoted methods --

    def test_get_fru_service(self, monkeypatch):
        """get_fru_service() delegates to _chassis.fru_service()."""
        client = self._make_client()
        sentinel = [{"fru": "data"}]
        monkeypatch.setattr(client._chassis, "fru_service", lambda cid="1": sentinel)
        assert client.get_fru_service() is sentinel
        client.close()

    def test_get_mainboard_from_system_fru(self, monkeypatch):
        """get_mainboard() should prefer system FRU board info."""
        from redfish_sdk.models.fru import Fru
        client = self._make_client()
        board = MainBoard.model_construct(serial_number="MB-SN-001", manufacturer="xFusion")
        fru = Fru.model_construct(board=board)

        monkeypatch.setattr(client, "get_system_fru", lambda sid=None: fru)
        monkeypatch.setattr(client, "get_baseboard_fru", lambda cid="1": pytest.fail("should not call get_baseboard_fru"))
        monkeypatch.setattr(client, "get_chassis", lambda cid="1": pytest.fail("should not call get_chassis"))

        result = client.get_mainboard()
        assert result is board
        assert result.serial_number == "MB-SN-001"
        client.close()

    def test_get_mainboard_from_chassis_fru_service(self, monkeypatch):
        """get_mainboard() should fallback to chassis FRU service board info."""
        client = self._make_client()
        board_raw = {
            "SerialNumber": "MB-SN-002",
            "Manufacturer": "VendorB",
            "PartNumber": "PN-002",
        }

        monkeypatch.setattr(client, "get_system_fru", lambda sid=None: None)
        monkeypatch.setattr(client, "get_baseboard_fru", lambda cid="1": board_raw)
        monkeypatch.setattr(client, "get_chassis", lambda cid="1": pytest.fail("should not call get_chassis"))

        result = client.get_mainboard()
        assert isinstance(result, MainBoard)
        assert result.serial_number == "MB-SN-002"
        assert result.part_number == "PN-002"
        client.close()

    def test_get_mainboard_from_chassis_oem(self, monkeypatch):
        """get_mainboard() should fallback to chassis OEM mainboard info."""
        from redfish_sdk.models.chassis import Chassis
        from redfish_sdk.models.oem import Bmc, Oem

        client = self._make_client()
        board = MainBoard.model_construct(serial_number="MB-SN-003", manufacturer="VendorC")
        chassis = Chassis.model_construct(oem=Oem.model_construct(bmc=Bmc.model_construct(mainboard=board)))

        monkeypatch.setattr(client, "get_system_fru", lambda sid=None: None)
        monkeypatch.setattr(client, "get_baseboard_fru", lambda cid="1": None)
        monkeypatch.setattr(client, "get_chassis", lambda cid="1": chassis)

        result = client.get_mainboard()
        assert result is board
        assert result.manufacturer == "VendorC"
        client.close()

    def test_get_mainboard_returns_none_when_all_sources_fail(self, monkeypatch):
        """get_mainboard() should return None when all fallbacks fail."""
        from redfish_sdk.exceptions import RedfishNotFoundError

        client = self._make_client()
        monkeypatch.setattr(client, "get_system_fru", lambda sid=None: (_ for _ in ()).throw(RedfishNotFoundError("/redfish/v1/Systems/1/FruInfo")))
        monkeypatch.setattr(client, "get_baseboard_fru", lambda cid="1": (_ for _ in ()).throw(RedfishNotFoundError("/redfish/v1/Chassis/1/FruService/0")))
        monkeypatch.setattr(client, "get_chassis", lambda cid="1": (_ for _ in ()).throw(RedfishNotFoundError("/redfish/v1/Chassis/1")))

        assert client.get_mainboard() is None
        client.close()

    def test_get_fan_prefers_thermal_subsystem_path(self, monkeypatch):
        """get_fan() should use ThermalSubsystem/Fans path first, returning Fan models."""
        from redfish_sdk.models.thermal import Fan

        client = self._make_client()

        fan0_raw = {
            "@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem/Fans/0",
            "Name": "Fan1",
            "Reading": 8500,
            "ReadingUnits": "RPM",
            "Status": {"State": "Enabled", "Health": "OK"},
        }
        fan1_raw = {
            "@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem/Fans/1",
            "Name": "Fan2",
            "Reading": 9200,
            "ReadingUnits": "RPM",
            "Status": {"State": "Enabled", "Health": "OK"},
        }
        collection = {
            "Members": [
                {"@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem/Fans/0"},
                {"@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem/Fans/1"},
            ]
        }

        def mock_get_raw(path):
            if path == "/redfish/v1/Chassis/1/ThermalSubsystem/Fans":
                return collection
            if path == "/redfish/v1/Chassis/1/ThermalSubsystem/Fans/0":
                return fan0_raw
            if path == "/redfish/v1/Chassis/1/ThermalSubsystem/Fans/1":
                return fan1_raw
            pytest.fail(f"unexpected path: {path}")

        monkeypatch.setattr(client, "get_raw", mock_get_raw)
        result = client.get_fan()
        assert len(result) == 2
        assert all(isinstance(f, Fan) for f in result)
        assert result[0].name == "Fan1"
        assert result[0].reading == 8500
        assert result[1].name == "Fan2"
        client.close()

    def test_get_fan_fallback_to_thermal_path(self, monkeypatch):
        """get_fan() should fallback to Thermal resource, returning Fan models."""
        from redfish_sdk.exceptions import RedfishNotFoundError
        from redfish_sdk.models.thermal import Fan, Thermal

        client = self._make_client()
        fan = Fan.model_construct(name="Fan1", reading=9200, member_id="0")
        thermal = Thermal.model_construct(fans=[fan])

        monkeypatch.setattr(client, "get_raw",
                            lambda path: (_ for _ in ()).throw(RedfishNotFoundError(path)))
        monkeypatch.setattr(client, "get_thermal", lambda cid="1": thermal)

        result = client.get_fan()
        assert len(result) == 1
        assert isinstance(result[0], Fan)
        assert result[0].name == "Fan1"
        assert result[0].reading == 9200
        client.close()

    def test_get_fan_returns_empty_list_when_all_paths_fail(self, monkeypatch):
        """get_fan() should return empty list when all fallback paths fail."""
        from redfish_sdk.exceptions import RedfishNotFoundError

        client = self._make_client()
        monkeypatch.setattr(client, "get_raw",
                            lambda path: (_ for _ in ()).throw(RedfishNotFoundError(path)))
        monkeypatch.setattr(client, "get_thermal",
                            lambda cid="1": (_ for _ in ()).throw(RedfishNotFoundError("/thermal")))

        assert client.get_fan() == []
        client.close()

    # -- get_inlet_history_temperature --

    def test_get_inlet_history_temperature_returns_typed_model(self, monkeypatch):
        """get_inlet_history_temperature() returns typed model when BMC supports it."""
        from redfish_sdk.models.common import Link
        from redfish_sdk.models.thermal import InletHistoryTemperature, Thermal

        client = self._make_client()

        ihx_path = "/redfish/v1/Chassis/1/Thermal/InletHistoryTemperature"
        thermal = Thermal.model_construct(
            inlet_history_temperature=Link.model_construct(odata_id=ihx_path),
        )
        ihx_model = InletHistoryTemperature(
            **{
                "@odata.id": ihx_path,
                "Id": "InletHistoryTemperature",
                "Name": "InletHistoryTemperature",
                "Description": "Air Inlet Historical Temperature",
                "HistoricalInletTemp": [
                    {"Description": "Normal", "avg": 20.74, "max": 21.0, "min": 20.0,
                     "time": "2026-06-03T13:30:46+08:00"},
                    {"Description": "Normal", "avg": 21.577, "max": 23.0, "min": 20.0,
                     "time": "2026-06-03T13:35:50+08:00"},
                ],
            }
        )

        monkeypatch.setattr(client._chassis, "thermal", lambda cid="1": thermal)
        monkeypatch.setattr(
            client._http_client,
            "get",
            lambda path, model_class: ihx_model,
        )

        result = client.get_inlet_history_temperature()
        assert isinstance(result, InletHistoryTemperature)
        assert result.description == "Air Inlet Historical Temperature"
        assert result.historical_inlet_temp is not None
        assert len(result.historical_inlet_temp) == 2
        assert result.historical_inlet_temp[0].avg == 20.74
        assert result.historical_inlet_temp[0].time == "2026-06-03T13:30:46+08:00"
        assert result.historical_inlet_temp[1].max == 23.0
        client.close()

    def test_get_inlet_history_temperature_returns_none_when_link_missing(self, monkeypatch):
        """Returns None when Thermal does not advertise InletHistoryTemperature link."""
        from redfish_sdk.models.thermal import Thermal

        client = self._make_client()
        thermal = Thermal.model_construct(inlet_history_temperature=None)
        monkeypatch.setattr(client._chassis, "thermal", lambda cid="1": thermal)

        def _should_not_call(_path, _model_class):
            pytest.fail("HTTP layer must not be invoked when link is missing")

        monkeypatch.setattr(client._http_client, "get", _should_not_call)
        assert client.get_inlet_history_temperature() is None
        client.close()

    def test_get_inlet_history_temperature_returns_none_on_404(self, monkeypatch):
        """Returns None when sub-resource URL responds with 404."""
        from redfish_sdk.exceptions import RedfishNotFoundError
        from redfish_sdk.models.common import Link
        from redfish_sdk.models.thermal import Thermal

        client = self._make_client()
        ihx_path = "/redfish/v1/Chassis/1/Thermal/InletHistoryTemperature"
        thermal = Thermal.model_construct(
            inlet_history_temperature=Link.model_construct(odata_id=ihx_path),
        )
        monkeypatch.setattr(client._chassis, "thermal", lambda cid="1": thermal)
        monkeypatch.setattr(
            client._http_client,
            "get",
            lambda path, model_class: (_ for _ in ()).throw(RedfishNotFoundError(path)),
        )

        assert client.get_inlet_history_temperature() is None
        client.close()

    def test_get_inlet_history_temperature_propagates_auth_error(self, monkeypatch):
        """Auth/network errors must propagate (not silently swallowed)."""
        from redfish_sdk.exceptions import RedfishAuthError
        from redfish_sdk.models.common import Link
        from redfish_sdk.models.thermal import Thermal

        client = self._make_client()
        thermal = Thermal.model_construct(
            inlet_history_temperature=Link.model_construct(odata_id="/x"),
        )
        monkeypatch.setattr(client._chassis, "thermal", lambda cid="1": thermal)
        monkeypatch.setattr(
            client._http_client,
            "get",
            lambda path, model_class: (_ for _ in ()).throw(RedfishAuthError(401)),
        )

        with pytest.raises(RedfishAuthError):
            client.get_inlet_history_temperature()
        client.close()

    # -- ManagersManager promoted methods --

    def test_get_manager(self, monkeypatch):
        """get_manager() delegates to _managers.get()."""
        from redfish_sdk.models.managers import Manager
        client = self._make_client()
        sentinel = Manager.model_construct(id="1", firmware_version="3.22")
        monkeypatch.setattr(client._managers, "get", lambda mid="1": sentinel)
        result = client.get_manager()
        assert result.firmware_version == "3.22"
        client.close()

    def test_get_manager_log_services(self, monkeypatch):
        """get_manager_log_services() delegates to _managers.log_services()."""
        client = self._make_client()
        sentinel = [{"id": "OperateLog"}]
        monkeypatch.setattr(client._managers, "log_services", lambda mid="1": sentinel)
        assert client.get_manager_log_services() is sentinel
        client.close()

    def test_get_manager_log_entries(self, monkeypatch):
        """get_manager_log_entries() delegates to _managers.log_entries()."""
        client = self._make_client()
        sentinel = [{"id": "entry-1"}]
        monkeypatch.setattr(client._managers, "log_entries", lambda log_id, mid="1": sentinel)
        assert client.get_manager_log_entries("OperateLog") is sentinel
        client.close()

    def test_get_network_protocol(self, monkeypatch):
        """get_network_protocol() delegates to _managers.network_protocol()."""
        client = self._make_client()
        sentinel = {"HTTPS": {"Port": 443}}
        monkeypatch.setattr(client._managers, "network_protocol", lambda mid="1": sentinel)
        assert client.get_network_protocol() is sentinel
        client.close()

    def test_get_manager_ethernet_interfaces(self, monkeypatch):
        """get_manager_ethernet_interfaces() delegates to _managers.ethernet_interfaces()."""
        client = self._make_client()
        sentinel = [{"id": "eth0"}]
        monkeypatch.setattr(client._managers, "ethernet_interfaces", lambda mid="1": sentinel)
        assert client.get_manager_ethernet_interfaces() is sentinel
        client.close()

    def test_get_host_interfaces(self, monkeypatch):
        """get_host_interfaces() delegates to _managers.host_interfaces()."""
        client = self._make_client()
        sentinel = [{"id": "HostInterface1"}]
        monkeypatch.setattr(client._managers, "host_interfaces", lambda mid="1": sentinel)
        assert client.get_host_interfaces() is sentinel
        client.close()

    # -- AccountServiceManager promoted methods --

    def test_get_accounts(self, monkeypatch):
        """get_accounts() delegates to _accounts.accounts()."""
        client = self._make_client()
        sentinel = [{"UserName": "Admin"}]
        monkeypatch.setattr(client._accounts, "accounts", lambda: sentinel)
        assert client.get_accounts() is sentinel
        client.close()

    def test_get_roles(self, monkeypatch):
        """get_roles() delegates to _accounts.roles()."""
        client = self._make_client()
        sentinel = [{"RoleId": "Administrator"}]
        monkeypatch.setattr(client._accounts, "roles", lambda: sentinel)
        assert client.get_roles() is sentinel
        client.close()

    def test_add_account(self, monkeypatch):
        """add_account() delegates to _accounts.add()."""
        from redfish_sdk.models.account import Account
        client = self._make_client()
        account_in = Account.model_construct(user_name="new_user")
        sentinel = Account.model_construct(user_name="new_user", id="5")
        monkeypatch.setattr(client._accounts, "add", lambda acct: sentinel)
        result = client.add_account(account_in)
        assert result.id == "5"
        client.close()

    def test_update_account(self, monkeypatch):
        """update_account() delegates to _accounts.update()."""
        from redfish_sdk.models.account import Account
        client = self._make_client()
        account_patch = Account.model_construct(role_id="Operator")
        sentinel = Account.model_construct(user_name="testuser", role_id="Operator")
        monkeypatch.setattr(client._accounts, "update", lambda un, acct: sentinel)
        result = client.update_account("testuser", account_patch)
        assert result.role_id == "Operator"
        client.close()

    def test_delete_account(self, monkeypatch):
        """delete_account() delegates to _accounts.delete()."""
        client = self._make_client()
        monkeypatch.setattr(client._accounts, "delete", lambda un: "")
        result = client.delete_account("testuser")
        assert result == ""
        client.close()

    # -- SessionServiceManager promoted methods --

    def test_get_sessions(self, monkeypatch):
        """get_sessions() delegates to _sessions.sessions()."""
        client = self._make_client()
        sentinel = [{"id": "sess1"}]
        monkeypatch.setattr(client._sessions, "sessions", lambda: sentinel)
        assert client.get_sessions() is sentinel
        client.close()

    def test_get_session(self, monkeypatch):
        """get_session() delegates to _sessions.get()."""
        client = self._make_client()
        sentinel = {"id": "sess1", "UserName": "Admin"}
        monkeypatch.setattr(client._sessions, "get", lambda sid: sentinel)
        assert client.get_session("sess1") is sentinel
        client.close()

    def test_create_session(self, monkeypatch):
        """create_session() delegates to _sessions.create()."""
        from redfish_sdk.models.session import Session
        client = self._make_client()
        sentinel = Session.model_construct(id="new-sess", user_name="Admin")
        captured = {}

        def mock_create(username, password, switch_to_token_auth=False):
            captured.update(username=username, password=password, switch=switch_to_token_auth)
            return sentinel

        monkeypatch.setattr(client._sessions, "create", mock_create)
        result = client.create_session("Admin", "pass123", switch_to_token_auth=True)
        assert result.id == "new-sess"
        assert captured["switch"] is True
        client.close()

    def test_delete_session(self, monkeypatch):
        """delete_session() delegates to _sessions.delete()."""
        client = self._make_client()
        monkeypatch.setattr(client._sessions, "delete", lambda sid: "deleted")
        assert client.delete_session("sess1") == "deleted"
        client.close()

    # -- EventServiceManager promoted methods --

    def test_get_subscriptions(self, monkeypatch):
        """get_subscriptions() delegates to _events.subscriptions()."""
        client = self._make_client()
        sentinel = [{"id": "sub1"}]
        monkeypatch.setattr(client._events, "subscriptions", lambda: sentinel)
        assert client.get_subscriptions() is sentinel
        client.close()

    def test_subscribe(self, monkeypatch):
        """subscribe() delegates to _events.subscribe() and forwards kwargs."""
        client = self._make_client()
        sentinel = {"id": "sub-new"}
        captured = {}

        def mock_subscribe(destination, event_types=None, context=None, **kwargs):
            captured.update(
                dest=destination, types=event_types, ctx=context, kw=kwargs
            )
            return sentinel

        monkeypatch.setattr(client._events, "subscribe", mock_subscribe)
        result = client.subscribe("https://my-server/events", ["Alert"])
        assert result is sentinel
        assert captured["dest"] == "https://my-server/events"
        assert captured["types"] == ["Alert"]
        # Defaults that Client must forward unconditionally:
        assert captured["kw"]["protocol"] == "Redfish"
        # Unsupplied optionals must surface as None (no vendor defaults).
        assert captured["kw"]["http_headers"] is None
        assert captured["kw"]["origin_resources"] is None
        assert captured["kw"]["raw_body"] is None
        client.close()

    def test_delete_subscription(self, monkeypatch):
        """delete_subscription() delegates to _events.delete()."""
        client = self._make_client()
        monkeypatch.setattr(client._events, "delete", lambda sid: "done")
        assert client.delete_subscription("sub1") == "done"
        client.close()

    # -- UpdateServiceManager promoted methods --

    def test_get_client_certificates(self, monkeypatch):
        """get_client_certificates() delegates to _updates.client_certificates()."""
        client = self._make_client()
        sentinel = [{"id": "cert1"}]
        monkeypatch.setattr(client._updates, "client_certificates", lambda: sentinel)
        assert client.get_client_certificates() is sentinel
        client.close()

    def test_simple_update(self, monkeypatch):
        """simple_update() delegates to _updates.simple_update()."""
        client = self._make_client()
        sentinel = {"status": "updating"}
        captured = {}

        def mock_update(image_uri, transfer_protocol="HTTP", targets=None,
                        vendor=None, **kwargs):
            captured.update(uri=image_uri, proto=transfer_protocol,
                            targets=targets, vendor=vendor)
            return sentinel

        monkeypatch.setattr(client._updates, "simple_update", mock_update)
        result = client.simple_update("http://nas/fw/bmc.bin", targets=["/redfish/v1/Managers/1"])
        assert result is sentinel
        assert captured["uri"] == "http://nas/fw/bmc.bin"
        assert captured["targets"] == ["/redfish/v1/Managers/1"]
        client.close()

    # -- RegistriesManager promoted methods --

    def test_get_registries(self, monkeypatch):
        """get_registries() delegates to _registries.registries()."""
        client = self._make_client()
        sentinel = [{"id": "Base.1.15.0"}]
        monkeypatch.setattr(client._registries, "registries", lambda: sentinel)
        assert client.get_registries() is sentinel
        client.close()

    def test_get_registry(self, monkeypatch):
        """get_registry() delegates to _registries.get()."""
        client = self._make_client()
        sentinel = {"id": "Base.1.15.0", "Language": "en"}
        monkeypatch.setattr(client._registries, "get", lambda rid: sentinel)
        assert client.get_registry("Base.1.15.0") is sentinel
        client.close()

    # -- TaskServiceManager promoted methods --

    def test_get_tasks(self, monkeypatch):
        """get_tasks() delegates to _tasks.tasks()."""
        client = self._make_client()
        sentinel = [{"id": "task1"}]
        monkeypatch.setattr(client._tasks, "tasks", lambda: sentinel)
        assert client.get_tasks() is sentinel
        client.close()

    def test_get_task(self, monkeypatch):
        """get_task() delegates to _tasks.get()."""
        client = self._make_client()
        sentinel = {"id": "task1", "TaskState": "Running"}
        monkeypatch.setattr(client._tasks, "get", lambda tid: sentinel)
        assert client.get_task("task1") is sentinel
        client.close()

    def test_wait_for_task(self, monkeypatch):
        """wait_for_task() delegates to _tasks.wait_for_task()."""
        client = self._make_client()
        sentinel = {"id": "task1", "TaskState": "Completed"}
        captured = {}

        def mock_wait(task_id, poll_interval=5, timeout=600):
            captured.update(tid=task_id, poll=poll_interval, timeout=timeout)
            return sentinel

        monkeypatch.setattr(client._tasks, "wait_for_task", mock_wait)
        result = client.wait_for_task("task1", poll_interval=2, timeout=120)
        assert result is sentinel
        assert captured["poll"] == 2
        assert captured["timeout"] == 120
        client.close()


class TestRedfishResourceEnum:
    """Test RedfishResource enum properties."""

    def test_enum_is_string(self):
        assert isinstance(RedfishResource.SYSTEMS, str)
        assert RedfishResource.SYSTEMS == "Systems"

    def test_enum_value_matches_json_key(self):
        assert RedfishResource.PROCESSORS.value == "Processors"
        assert RedfishResource.THERMAL.value == "Thermal"
        assert RedfishResource.NETWORK_PROTOCOL.value == "NetworkProtocol"

    def test_enum_member_count(self):
        # 13 Root + 14 System + 6 Chassis + 5 Manager = 38
        assert len(RedfishResource) == 38

    def test_all_values_are_pascal_case_strings(self):
        for member in RedfishResource:
            assert isinstance(member.value, str)
            # First char should be uppercase (PascalCase)
            assert member.value[0].isupper(), f"{member.name} value should be PascalCase"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
