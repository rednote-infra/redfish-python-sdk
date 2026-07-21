"""
Update strategies for multi-vendor firmware update support.

This package implements the Strategy Pattern for SimpleUpdate, allowing
each server vendor to have its own body-construction logic while keeping
a single entry point in UpdateServiceManager.simple_update().

Architecture:
    BaseUpdateStrategy (ABC)
      ├── GenericUpdateStrategy   — standard Redfish fallback
      ├── InspurUpdateStrategy    — Inspur (浪潮)
      ├── ZteUpdateStrategy       — ZTE (中兴)
      ├── H3cUpdateStrategy       — H3C (新华三)
      ├── NettrixUpdateStrategy   — Nettrix (宁畅)
      ├── XFusionUpdateStrategy   — xFusion (超聚变)
      └── LenovoUpdateStrategy    — Lenovo (联想)

All strategies are auto-registered when this package is imported.
"""

from .base import BaseUpdateStrategy, GenericUpdateStrategy
from .h3c import H3cUpdateStrategy
from .inspur import InspurUpdateStrategy
from .lenovo import LenovoUpdateStrategy
from .nettrix import NettrixUpdateStrategy
from .registry import UpdateStrategyRegistry
from .vendor_detect import VendorDetector
from .xfusion import XFusionUpdateStrategy
from .zte import ZteUpdateStrategy

# --- Auto-register all vendor strategies ---
UpdateStrategyRegistry.register("generic", GenericUpdateStrategy())
UpdateStrategyRegistry.register("inspur", InspurUpdateStrategy())
UpdateStrategyRegistry.register("zte", ZteUpdateStrategy())
UpdateStrategyRegistry.register("h3c", H3cUpdateStrategy())
UpdateStrategyRegistry.register("nettrix", NettrixUpdateStrategy())
UpdateStrategyRegistry.register("xfusion", XFusionUpdateStrategy())
UpdateStrategyRegistry.register("lenovo", LenovoUpdateStrategy())

__all__ = [
    "BaseUpdateStrategy",
    "GenericUpdateStrategy",
    "InspurUpdateStrategy",
    "ZteUpdateStrategy",
    "H3cUpdateStrategy",
    "NettrixUpdateStrategy",
    "XFusionUpdateStrategy",
    "LenovoUpdateStrategy",
    "UpdateStrategyRegistry",
    "VendorDetector",
]
