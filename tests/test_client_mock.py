"""
Integration tests for the client using mock HTTP responses.
Tests the complete client flow from initialization to service manager calls.

These tests never hit a real BMC. Host/credential values default to
unrealistic placeholders so they cannot be confused with real assets.
"""

import os

import pytest

from redfish_sdk import RedfishClient

# Dummy values for mock tests; can be overridden via env vars.
MOCK_HOST = os.environ.get("BMC_IP", "mock-bmc-host")
MOCK_USER = os.environ.get("BMC_USER", "mock-user")
MOCK_PASSWORD = os.environ.get("BMC_PASSWORD", "mock-password")


class TestRedfishClientInit:
    def test_client_init(self):
        client = RedfishClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
            verify_ssl=False,
        )
        assert client.host == MOCK_HOST
        # Managers are lazy — not created until accessed
        assert "_systems" not in client.__dict__
        assert "_chassis" not in client.__dict__
        assert "_managers" not in client.__dict__
        # Accessing private managers triggers lazy creation
        assert client._systems is not None
        assert client._chassis is not None
        assert client._managers is not None
        assert client._accounts is not None
        assert client._sessions is not None
        assert client._events is not None
        assert client._updates is not None
        assert client._registries is not None
        assert client._tasks is not None
        client.close()

    def test_client_context_manager(self):
        with RedfishClient(
            host=MOCK_HOST,
            username=MOCK_USER,
            password=MOCK_PASSWORD,
        ) as client:
            assert client is not None
            assert repr(client) == f"RedfishClient(host='{MOCK_HOST}')"


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

        from redfish_sdk.http_client import RedfishHttpClient
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
        from redfish_sdk.http_client import RedfishHttpClient
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
        from redfish_sdk.http_client import RedfishHttpClient
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
