"""
OEM extractor registry — maps vendor keys to extractor instances.

Strategies are registered at package import time. The registry returns
the extractor for a detected vendor, falling back to
:class:`GenericOemExtractor` for unknown vendors.

Mirrors :class:`LogCollectStrategyRegistry` in the sibling
``log_collect_strategies`` package.
"""
from __future__ import annotations

import logging
from typing import Dict

from .base import BaseOemExtractor, GenericOemExtractor

logger = logging.getLogger(__name__)

# Singleton fallback for unknown vendors.
_GENERIC_EXTRACTOR = GenericOemExtractor()


class OemExtractorRegistry:
    """
    Registry mapping vendor keys to OEM extractor instances.

    Usage:
        # Registration (done at package import time)
        OemExtractorRegistry.register("xfusion", XFusionOemExtractor())

        # Lookup
        extractor = OemExtractorRegistry.get("xfusion")
        ratio = extractor.get_fan_speed_ratio(fan)
    """

    _extractors: Dict[str, BaseOemExtractor] = {}

    @classmethod
    def register(cls, vendor: str, extractor: BaseOemExtractor) -> None:
        """Register an extractor for a vendor key (case-insensitive)."""
        cls._extractors[vendor.lower()] = extractor
        logger.debug("Registered OEM extractor for vendor: %s", vendor)

    @classmethod
    def get(cls, vendor: str) -> BaseOemExtractor:
        """
        Return the extractor for a vendor, or the generic fallback.

        Args:
            vendor: Vendor key (case-insensitive). Expected values match
                :class:`VendorDetector` output — ``"xfusion"`` /
                ``"inspur"`` / ``"lenovo"`` / ``"nettrix"`` / ``"h3c"`` /
                ``"zte"`` / ``"smoothcompute"`` / ``"generic"``.
        """
        extractor = cls._extractors.get(vendor.lower())
        if extractor is None:
            logger.warning(
                "No OEM extractor registered for vendor '%s', "
                "using generic Redfish extractor",
                vendor,
            )
            return _GENERIC_EXTRACTOR
        return extractor

    @classmethod
    def registered_vendors(cls) -> list:
        """Return the list of registered vendor keys."""
        return list(cls._extractors.keys())
