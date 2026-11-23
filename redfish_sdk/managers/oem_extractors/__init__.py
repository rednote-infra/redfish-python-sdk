"""
OEM extractors for multi-vendor Redfish telemetry and history resource links.

This package implements the Strategy Pattern for reading vendor-specific
fields out of the ``Oem`` payload on Fan and Drive resources, so the
model layer (``redfish_sdk.models``) stays vendor-agnostic — no
per-vendor typed fields on :class:`Bmc`, no hard-coded vendor list in
the merge logic.

Architecture:
    BaseOemExtractor (ABC)
      ├── GenericOemExtractor      — DMTF default (Reading/MaxReadingRange
      │                              for fan; no drive temperature)
      ├── XFusionOemExtractor      — Oem.xFusion.{SpeedRatio,
      │                              TemperatureCelsius}
      ├── InspurOemExtractor       — Oem.gOemCustomeString / Public.SpeedRatio
      │                              + Oem.Public.temperature (lowercase)
      ├── LenovoOemExtractor       — Reading/Max fallback for fan +
      │                              Oem.Public.temperature (lowercase)
      ├── NettrixOemExtractor      — Oem.Public.SpeedRatio (or Reading/Max)
      │                              + top-level Drive.DiskTemperatureCelsius
      ├── H3cOemExtractor          — Oem.Public.SpeedRatio +
      │                              Oem.Public.TemperatureCelsius
      └── ZteOemExtractor          — same shape as H3C

Vendors whose readings match the DMTF default (e.g. an unknown vendor
whose fan exposes a usable ``Reading``/``MaxReadingRange`` pair) fall
back to :class:`GenericOemExtractor` via the registry.

Vendor detection is shared with the ``update_strategies`` and
``log_collect_strategies`` packages via :class:`VendorDetector`.

All extractors are auto-registered when this package is imported.
"""
from ..update_strategies.vendor_detect import VendorDetector
from .ami import AMI_OEM_VENDOR, AmiOemExtractor
from .base import GENERIC_OEM_VENDOR, BaseOemExtractor, GenericOemExtractor
from .h3c import H3cOemExtractor
from .inspur import InspurOemExtractor
from .lenovo import LenovoOemExtractor
from .nettrix import NettrixOemExtractor
from .registry import OemExtractorRegistry
from .xfusion import XFusionOemExtractor
from .zte import ZteOemExtractor

# --- Auto-register the vendor extractors ---
OemExtractorRegistry.register(GENERIC_OEM_VENDOR, GenericOemExtractor())
OemExtractorRegistry.register(AMI_OEM_VENDOR, AmiOemExtractor())
OemExtractorRegistry.register("xfusion", XFusionOemExtractor())
OemExtractorRegistry.register("inspur", InspurOemExtractor())
OemExtractorRegistry.register("lenovo", LenovoOemExtractor())
OemExtractorRegistry.register("nettrix", NettrixOemExtractor())
OemExtractorRegistry.register("h3c", H3cOemExtractor())
OemExtractorRegistry.register("zte", ZteOemExtractor())

__all__ = [
    "BaseOemExtractor",
    "GenericOemExtractor",
    "AmiOemExtractor",
    "XFusionOemExtractor",
    "InspurOemExtractor",
    "LenovoOemExtractor",
    "NettrixOemExtractor",
    "H3cOemExtractor",
    "ZteOemExtractor",
    "OemExtractorRegistry",
    "VendorDetector",
]
