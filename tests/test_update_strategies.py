"""
Unit tests for multi-vendor firmware update strategies.

Tests cover:
- BaseUpdateStrategy action target discovery
- GenericUpdateStrategy body construction
- All 6 vendor strategies body construction
- VendorDetector identification logic
- UpdateStrategyRegistry registration and lookup
- Entry-point backward compatibility
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from redfish_sdk.managers.update_strategies import (
    GenericUpdateStrategy,
    UpdateStrategyRegistry,
    VendorDetector,
)
from redfish_sdk.managers.update_strategies.h3c import H3cUpdateStrategy
from redfish_sdk.managers.update_strategies.inspur import InspurUpdateStrategy
from redfish_sdk.managers.update_strategies.lenovo import LenovoUpdateStrategy
from redfish_sdk.managers.update_strategies.nettrix import NettrixUpdateStrategy
from redfish_sdk.managers.update_strategies.xfusion import XFusionUpdateStrategy
from redfish_sdk.managers.update_strategies.zte import ZteUpdateStrategy
from redfish_sdk.models.common import RedfishResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(manufacturer: str = "Generic") -> MagicMock:
    """Create a mock RedfishClient with configurable manufacturer."""
    client = MagicMock()

    # Mock _get_update_service
    update_svc = MagicMock()
    update_svc.odata_id = "/redfish/v1/UpdateService"
    client._get_update_service.return_value = update_svc

    # Mock _http_client.get_raw (returns Actions with SimpleUpdate target)
    client._http_client.get_raw.return_value = {
        "Actions": {
            "#UpdateService.SimpleUpdate": {
                "target": "/redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate"
            }
        }
    }

    # Mock _http_client.post (captures the body and returns a RedfishResponse)
    mock_response = MagicMock(spec=RedfishResponse)
    client._http_client.post.return_value = mock_response

    # Mock get_system for VendorDetector
    system = MagicMock()
    system.manufacturer = manufacturer
    system.oem = None
    client.get_system.return_value = system

    return client


def _get_posted_body(client: MagicMock) -> Dict[str, Any]:
    """Extract the raw_body from the last post() call."""
    args, kwargs = client._http_client.post.call_args
    return kwargs.get("raw_body", args[2] if len(args) > 2 else {})


# ===========================================================================
# TestUpdateStrategyRegistry
# ===========================================================================

class TestUpdateStrategyRegistry:
    """Tests for the strategy registry."""

    def test_registered_vendors_include_all_six(self):
        vendors = UpdateStrategyRegistry.registered_vendors()
        for v in ["inspur", "zte", "h3c", "nettrix", "xfusion", "lenovo", "generic"]:
            assert v in vendors, f"Vendor '{v}' not registered"

    def test_get_registered_vendor(self):
        strategy = UpdateStrategyRegistry.get("inspur")
        assert isinstance(strategy, InspurUpdateStrategy)

    def test_get_unknown_vendor_returns_generic(self):
        strategy = UpdateStrategyRegistry.get("unknown_vendor_xyz")
        assert isinstance(strategy, GenericUpdateStrategy)

    def test_get_is_case_insensitive(self):
        strategy = UpdateStrategyRegistry.get("INSPUR")
        assert isinstance(strategy, InspurUpdateStrategy)


# ===========================================================================
# TestVendorDetector
# ===========================================================================

class TestVendorDetector:
    """Tests for vendor auto-detection."""

    def setup_method(self):
        VendorDetector.clear_cache()

    def test_detect_inspur(self):
        client = _make_mock_client("Inspur")
        assert VendorDetector.detect(client) == "inspur"

    def test_detect_inspur_chinese(self):
        client = _make_mock_client("浪潮电子信息产业股份有限公司")
        assert VendorDetector.detect(client) == "inspur"

    def test_detect_inspur_maginfra(self):
        """Maginfra is an Inspur server brand — must be detected as inspur."""
        VendorDetector.clear_cache()
        client = _make_mock_client("Maginfra")
        assert VendorDetector.detect(client) == "inspur"

    def test_detect_zte(self):
        client = _make_mock_client("ZTE Corporation")
        assert VendorDetector.detect(client) == "zte"

    def test_detect_h3c(self):
        VendorDetector.clear_cache()
        client = _make_mock_client("H3C")
        assert VendorDetector.detect(client) == "h3c"

    def test_detect_nettrix(self):
        VendorDetector.clear_cache()
        client = _make_mock_client("Nettrix Information Industry")
        assert VendorDetector.detect(client) == "nettrix"

    def test_detect_xfusion(self):
        VendorDetector.clear_cache()
        client = _make_mock_client("xFusion Technologies")
        assert VendorDetector.detect(client) == "xfusion"

    def test_detect_lenovo(self):
        VendorDetector.clear_cache()
        client = _make_mock_client("Lenovo Global Technology")
        assert VendorDetector.detect(client) == "lenovo"

    def test_detect_unknown_returns_generic(self):
        VendorDetector.clear_cache()
        client = _make_mock_client("Some Unknown Vendor")
        assert VendorDetector.detect(client) == "generic"

    def test_detect_caches_result(self):
        VendorDetector.clear_cache()
        client = _make_mock_client("Inspur")
        assert VendorDetector.detect(client) == "inspur"
        # Second call should not hit get_system again
        client.get_system.reset_mock()
        assert VendorDetector.detect(client) == "inspur"
        client.get_system.assert_not_called()

    def test_clear_cache(self):
        VendorDetector.clear_cache()
        client = _make_mock_client("Inspur")
        VendorDetector.detect(client)
        VendorDetector.clear_cache()
        assert id(client) not in VendorDetector._cache


# ===========================================================================
# TestGenericUpdateStrategy
# ===========================================================================

class TestGenericUpdateStrategy:
    """Tests for the standard Redfish fallback strategy."""

    def test_basic_body(self):
        client = _make_mock_client()
        strategy = GenericUpdateStrategy()
        strategy.execute(client, "http://nas/fw/bmc.bin")

        body = _get_posted_body(client)
        assert body["ImageURI"] == "http://nas/fw/bmc.bin"
        assert body["TransferProtocol"] == "HTTP"
        assert "Targets" not in body
        assert "Oem" not in body

    def test_with_targets(self):
        client = _make_mock_client()
        strategy = GenericUpdateStrategy()
        strategy.execute(client, "http://nas/fw/bmc.bin",
                         targets=["/redfish/v1/Managers/1"])

        body = _get_posted_body(client)
        assert body["Targets"] == ["/redfish/v1/Managers/1"]

    def test_kwargs_ignored(self):
        client = _make_mock_client()
        strategy = GenericUpdateStrategy()
        strategy.execute(client, "http://nas/fw/bmc.bin",
                         preserve_config=True, flash_item="BMC")

        body = _get_posted_body(client)
        assert "preserve_config" not in body
        assert "flash_item" not in body
        assert "Oem" not in body


# ===========================================================================
# TestInspurUpdateStrategy
# ===========================================================================

class TestInspurUpdateStrategy:
    """Tests for Inspur (浪潮) strategy body construction."""

    def test_basic_body(self):
        client = _make_mock_client()
        strategy = InspurUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin")

        body = _get_posted_body(client)
        assert body["ImageURI"] == "https://nas/fw/bmc.bin"
        assert body["TransferProtocol"] == "HTTPS"
        assert "Oem" not in body

    def test_credentials(self):
        client = _make_mock_client()
        strategy = InspurUpdateStrategy()
        strategy.execute(client, "sftp://nas/fw/bmc.bin",
                         transfer_protocol="SFTP",
                         username="admin", password="secret")

        body = _get_posted_body(client)
        assert body["Username"] == "admin"
        assert body["Password"] == "secret"

    def test_oem_fields(self):
        client = _make_mock_client()
        strategy = InspurUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin",
                         flash_item="BMC",
                         preserve_config=True,
                         bios_update_type="FullBIOS",
                         bios_flash="Both")

        body = _get_posted_body(client)
        oem = body["Oem"]["Public"]
        assert oem["FlashItem"] == "BMC"
        assert oem["PreserveConf"] is True
        assert oem["BIOSUpdateType"] == "FullBIOS"
        assert oem["BiosFlash"] == "Both"

    def test_pfr_fields(self):
        client = _make_mock_client()
        strategy = InspurUpdateStrategy()
        strategy.execute(client, "https://nas/fw/pfr.bin",
                         pfr_type=True,
                         pfr_region="Region1",
                         pfr_update_dynamic=False,
                         seamless_module="BIOS_ONLY")

        body = _get_posted_body(client)
        oem = body["Oem"]["Public"]
        assert oem["PFRType"] is True
        assert oem["PFRRegion"] == "Region1"
        assert oem["PFRUpdateDynamic"] is False
        assert oem["SeamlessModule"] == "BIOS_ONLY"


# ===========================================================================
# TestZteUpdateStrategy
# ===========================================================================

class TestZteUpdateStrategy:
    """Tests for ZTE (中兴) strategy body construction."""

    def test_basic_body(self):
        client = _make_mock_client()
        strategy = ZteUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin")

        body = _get_posted_body(client)
        assert body["ImageURI"] == "https://nas/fw/bmc.bin"
        assert "Oem" not in body

    def test_oem_fields(self):
        client = _make_mock_client()
        strategy = ZteUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin",
                         preserve_config=True,
                         bmc_flash="Both",
                         bios_flash="Flash1",
                         apply_time="Immediate")

        body = _get_posted_body(client)
        oem = body["Oem"]["Public"]
        assert oem["PreserveConf"] is True
        assert oem["BMCFlash"] == "Both"
        assert oem["BiosFlash"] == "Flash1"
        assert oem["ApplyTime"] == "Immediate"


# ===========================================================================
# TestH3cUpdateStrategy
# ===========================================================================

class TestH3cUpdateStrategy:
    """Tests for H3C (新华三) strategy body construction."""

    def test_basic_body_no_transfer_protocol(self):
        """H3C should NOT include TransferProtocol in the body."""
        client = _make_mock_client()
        strategy = H3cUpdateStrategy()
        strategy.execute(client, "tftp://192.168.1.1/bmc.bin")

        body = _get_posted_body(client)
        assert body["ImageURI"] == "tftp://192.168.1.1/bmc.bin"
        assert "TransferProtocol" not in body

    def test_sftp_credential_embedding(self):
        """SFTP credentials should be embedded into the ImageURI."""
        client = _make_mock_client()
        strategy = H3cUpdateStrategy()
        strategy.execute(client, "sftp://192.168.1.1/fw/bmc.bin",
                         transfer_protocol="SFTP",
                         username="admin", password="secret")

        body = _get_posted_body(client)
        assert body["ImageURI"] == "sftp://admin:secret@192.168.1.1/fw/bmc.bin"

    def test_http_credentials_not_embedded(self):
        """HTTP credentials should NOT be embedded into the URI."""
        client = _make_mock_client()
        strategy = H3cUpdateStrategy()
        strategy.execute(client, "http://192.168.1.1/fw/bmc.bin",
                         transfer_protocol="HTTP",
                         username="admin", password="secret")

        body = _get_posted_body(client)
        # HTTP URIs do not embed credentials
        assert body["ImageURI"] == "http://192.168.1.1/fw/bmc.bin"

    def test_preserve_config_true(self):
        client = _make_mock_client()
        strategy = H3cUpdateStrategy()
        strategy.execute(client, "tftp://nas/bmc.bin", preserve_config=True)

        body = _get_posted_body(client)
        assert body["Oem"]["Public"]["Preserve"] == "Retain"

    def test_preserve_config_false(self):
        client = _make_mock_client()
        strategy = H3cUpdateStrategy()
        strategy.execute(client, "tftp://nas/bmc.bin", preserve_config=False)

        body = _get_posted_body(client)
        assert body["Oem"]["Public"]["Preserve"] == "Restore"

    def test_restore_mode_overrides_preserve_config(self):
        client = _make_mock_client()
        strategy = H3cUpdateStrategy()
        strategy.execute(client, "tftp://nas/bmc.bin",
                         preserve_config=True, restore_mode="ForceRestore")

        body = _get_posted_body(client)
        assert body["Oem"]["Public"]["Preserve"] == "ForceRestore"

    def test_oem_fields(self):
        client = _make_mock_client()
        strategy = H3cUpdateStrategy()
        strategy.execute(client, "tftp://nas/bmc.bin",
                         reboot_mode="Auto",
                         image_md5_uri="tftp://nas/MD5.txt",
                         upgrade_type="all",
                         delay="300")

        body = _get_posted_body(client)
        oem = body["Oem"]["Public"]
        assert oem["RebootMode"] == "Auto"
        assert oem["ImageMd5URI"] == "tftp://nas/MD5.txt"
        assert oem["UpgradeType"] == "all"
        assert oem["Date"] == "300"


# ===========================================================================
# TestNettrixUpdateStrategy
# ===========================================================================

class TestNettrixUpdateStrategy:
    """Tests for Nettrix (宁畅) strategy body construction."""

    def test_basic_body_with_targets(self):
        client = _make_mock_client()
        strategy = NettrixUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin",
                         targets=["ActiveBMC"])

        body = _get_posted_body(client)
        assert body["ImageURI"] == "https://nas/fw/bmc.bin"
        assert body["Targets"] == ["ActiveBMC"]

    def test_save_config_at_top_level(self):
        """SaveConfig should be at body top level, NOT under Oem."""
        client = _make_mock_client()
        strategy = NettrixUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin",
                         preserve_config=True)

        body = _get_posted_body(client)
        assert body["SaveConfig"] is True
        assert "Oem" not in body


# ===========================================================================
# TestXFusionUpdateStrategy
# ===========================================================================

class TestXFusionUpdateStrategy:
    """Tests for xFusion (超聚变) strategy body construction."""

    def test_basic_body(self):
        client = _make_mock_client()
        strategy = XFusionUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin")

        body = _get_posted_body(client)
        assert body["ImageURI"] == "https://nas/fw/bmc.bin"
        assert "Oem" not in body

    def test_extension_fields_at_top_level(self):
        """PreserveConfig and ActiveMode should be at body top level."""
        client = _make_mock_client()
        strategy = XFusionUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin",
                         preserve_config=True,
                         active_mode="Immediately",
                         module_array=["PSU1", "PSU2"])

        body = _get_posted_body(client)
        assert body["PreserveConfig"] is True
        assert body["ActiveMode"] == "Immediately"
        assert body["ModuleArray"] == ["PSU1", "PSU2"]
        assert "Oem" not in body


# ===========================================================================
# TestLenovoUpdateStrategy
# ===========================================================================

class TestLenovoUpdateStrategy:
    """Tests for Lenovo (联想) strategy body construction."""

    def test_basic_body_with_targets(self):
        client = _make_mock_client()
        strategy = LenovoUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin",
                         targets=["/redfish/v1/Managers/1"])

        body = _get_posted_body(client)
        assert body["ImageURI"] == "https://nas/fw/bmc.bin"
        assert body["Targets"] == ["/redfish/v1/Managers/1"]

    def test_credentials(self):
        client = _make_mock_client()
        strategy = LenovoUpdateStrategy()
        strategy.execute(client, "sftp://nas/fw/bmc.bin",
                         transfer_protocol="SFTP",
                         username="admin", password="secret")

        body = _get_posted_body(client)
        assert body["Username"] == "admin"
        assert body["Password"] == "secret"

    def test_no_credentials_no_extra_fields(self):
        client = _make_mock_client()
        strategy = LenovoUpdateStrategy()
        strategy.execute(client, "https://nas/fw/bmc.bin")

        body = _get_posted_body(client)
        assert "Username" not in body
        assert "Password" not in body
        assert "Oem" not in body


# ===========================================================================
# TestBackwardCompatibility
# ===========================================================================

class TestBackwardCompatibility:
    """Ensure the refactored simple_update is backward compatible."""

    def test_old_style_call_works(self):
        """Calling simple_update with only (image_uri) should work."""
        client = _make_mock_client("Some Unknown Vendor")
        VendorDetector.clear_cache()

        from redfish_sdk.managers.update import UpdateServiceManager
        mgr = UpdateServiceManager(client)
        mgr.simple_update("http://nas/fw/bmc.bin")

        body = _get_posted_body(client)
        assert body["ImageURI"] == "http://nas/fw/bmc.bin"
        assert body["TransferProtocol"] == "HTTP"

    def test_old_style_with_targets(self):
        """Calling with (image_uri, transfer_protocol, targets) works."""
        client = _make_mock_client("Some Unknown Vendor")
        VendorDetector.clear_cache()

        from redfish_sdk.managers.update import UpdateServiceManager
        mgr = UpdateServiceManager(client)
        mgr.simple_update(
            "http://nas/fw/bmc.bin", "NFS", ["/redfish/v1/Managers/1"]
        )

        body = _get_posted_body(client)
        assert body["ImageURI"] == "http://nas/fw/bmc.bin"
        assert body["TransferProtocol"] == "NFS"
        assert body["Targets"] == ["/redfish/v1/Managers/1"]

    def test_vendor_override(self):
        """Explicit vendor= should override auto-detection."""
        client = _make_mock_client("Some Unknown Vendor")
        VendorDetector.clear_cache()

        from redfish_sdk.managers.update import UpdateServiceManager
        mgr = UpdateServiceManager(client)
        mgr.simple_update(
            "https://nas/fw/bmc.bin",
            vendor="inspur",
            flash_item="BMC",
            preserve_config=True,
        )

        body = _get_posted_body(client)
        assert body["Oem"]["Public"]["FlashItem"] == "BMC"
        assert body["Oem"]["Public"]["PreserveConf"] is True
