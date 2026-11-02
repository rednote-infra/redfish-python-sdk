"""
Vendor detection for automatic update strategy routing.

Detects the server vendor at runtime by inspecting the System resource's
Manufacturer field, falling back to OEM key detection.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)

# Canonical vendor key -> list of known manufacturer substrings (lowercase)
_VENDOR_KEYWORDS: Dict[str, List[str]] = {
    # Unicode escapes preserve matching for localized manufacturer strings
    # while keeping the source and documentation English-only.
    "enginetech": ["enginetech", "\u5b89\u64ce"],
    "inspur": ["inspur", "\u6d6a\u6f6e", "maginfra"],
    "ieit": ["ieit systems"],
    "zte": ["zte", "\u4e2d\u5174"],
    "h3c": ["h3c", "\u65b0\u534e\u4e09", "h3c servers"],
    "nettrix": ["nettrix", "\u5b81\u7545"],
    "xfusion": ["xfusion", "\u8d85\u805a\u53d8", "huawei"],
    "lenovo": ["lenovo", "\u8054\u60f3"],
    # Vendor and System.Manufacturer both report "smoothcompute" on the
    # 6415 X2 family and similar SKUs.
    "smoothcompute": ["smoothcompute", "\u987a\u7b97"],
}


class VendorDetector:
    """
    Detects the server vendor from the Redfish System resource.

    Detection order:
    1. System.Manufacturer field (primary)
    2. OEM key names in the System resource (fallback)

    Results are cached per client instance to avoid repeated HTTP calls.
    """

    # Cache: client id -> detected vendor string
    _cache: Dict[int, str] = {}

    @classmethod
    def detect(cls, client: RedfishClient) -> str:
        """
        Detect the server vendor for the given client.

        Args:
            client: RedfishClient instance

        Returns:
            Canonical vendor key (e.g., "inspur", "zte") or "generic"
        """
        client_id = id(client)
        if client_id in cls._cache:
            return cls._cache[client_id]

        vendor = cls._detect_from_system(client)
        cls._cache[client_id] = vendor

        if vendor == "generic":
            logger.warning(
                "Could not detect server vendor, falling back to generic strategy"
            )
        else:
            logger.info("Detected server vendor: %s", vendor)

        return vendor

    @classmethod
    def _detect_from_system(cls, client: RedfishClient) -> str:
        """Attempt detection from System.Manufacturer."""
        try:
            system = client.get_system()
            manufacturer = (system.manufacturer or "").lower().strip()

            if manufacturer:
                for vendor_key, keywords in _VENDOR_KEYWORDS.items():
                    for keyword in keywords:
                        if keyword.lower() in manufacturer:
                            return vendor_key

            # Fallback: check OEM keys in the raw system response
            return cls._detect_from_oem_keys(client)
        except Exception:
            logger.debug("Vendor detection from System failed, trying OEM keys")
            return cls._detect_from_oem_keys(client)

    @classmethod
    def _detect_from_oem_keys(cls, client: RedfishClient) -> str:
        """Fallback: detect vendor from OEM key names in System resource."""
        try:
            system = client.get_system()
            if system.oem and system.oem.model_extra:
                extra_keys = {k.lower() for k in system.oem.model_extra}
                if "lenovo" in extra_keys:
                    return "lenovo"
                if "xfusion" in extra_keys:
                    return "xfusion"
                if "hpe" in extra_keys or "hp" in extra_keys:
                    return "generic"  # HPE not adapted yet
                if "dell" in extra_keys:
                    return "generic"  # Dell not adapted yet
        except Exception:
            logger.debug("Vendor detection from OEM keys failed")

        return "generic"

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the vendor detection cache."""
        cls._cache.clear()
