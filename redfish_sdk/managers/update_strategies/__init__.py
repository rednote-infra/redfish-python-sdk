"""
Update strategies for multi-vendor firmware update support.

This package implements the Strategy Pattern for SimpleUpdate, allowing
each server vendor to have its own body-construction logic while keeping
a single entry point in UpdateServiceManager.simple_update().

Architecture:
    BaseUpdateStrategy (ABC)
      ├── GenericUpdateStrategy   — standard Redfish fallback
      ├── EnginetechUpdateStrategy — Enginetech
      ├── InspurUpdateStrategy    — Inspur
      ├── ZteUpdateStrategy       — ZTE
      ├── H3cUpdateStrategy       — H3C
      ├── NettrixUpdateStrategy   — Nettrix
      ├── XFusionUpdateStrategy   — xFusion
      └── LenovoUpdateStrategy    — Lenovo

All strategies are auto-registered when this package is imported.
"""

from .base import BaseUpdateStrategy, GenericUpdateStrategy
from .enginetech import EnginetechUpdateStrategy
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
UpdateStrategyRegistry.register("enginetech", EnginetechUpdateStrategy())
UpdateStrategyRegistry.register("inspur", InspurUpdateStrategy())
UpdateStrategyRegistry.register("zte", ZteUpdateStrategy())
UpdateStrategyRegistry.register("h3c", H3cUpdateStrategy())
UpdateStrategyRegistry.register("nettrix", NettrixUpdateStrategy())
UpdateStrategyRegistry.register("xfusion", XFusionUpdateStrategy())
UpdateStrategyRegistry.register("lenovo", LenovoUpdateStrategy())

__all__ = [
    "BaseUpdateStrategy",
    "GenericUpdateStrategy",
    "EnginetechUpdateStrategy",
    "InspurUpdateStrategy",
    "ZteUpdateStrategy",
    "H3cUpdateStrategy",
    "NettrixUpdateStrategy",
    "XFusionUpdateStrategy",
    "LenovoUpdateStrategy",
    "UpdateStrategyRegistry",
    "VendorDetector",
]
