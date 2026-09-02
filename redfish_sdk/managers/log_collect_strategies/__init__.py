"""
Log-collect strategies for multi-vendor out-of-band diagnostic log support.

This package implements the Strategy Pattern for
``#LogService.CollectDiagnosticData``, allowing each server vendor to have
its own body-construction and artifact-resolution logic while keeping a
single entry point in ``ManagersManager.collect_diagnostic_data()``.

Architecture:
    BaseLogCollectStrategy (ABC)
      ├── GenericLogCollectStrategy — standard Redfish fallback
      ├── XFusionLogCollectStrategy — xFusion (超聚变)
      ├── LenovoLogCollectStrategy  — Lenovo (联想)
      ├── InspurLogCollectStrategy  — Inspur (浪潮)
      ├── NettrixLogCollectStrategy — Nettrix (宁畅)
      └── ZteLogCollectStrategy     — ZTE (中兴)

H3C (新华三) is intentionally not registered here; its SDS log collection
differs significantly and falls back to the generic strategy for now.

Vendor detection is shared with the firmware ``update_strategies`` package
via :class:`VendorDetector`.

All strategies are auto-registered when this package is imported.
"""

from ..update_strategies.vendor_detect import VendorDetector
from .base import BaseLogCollectStrategy, GenericLogCollectStrategy
from .inspur import InspurLogCollectStrategy
from .lenovo import LenovoLogCollectStrategy
from .nettrix import NettrixLogCollectStrategy
from .registry import LogCollectStrategyRegistry
from .xfusion import XFusionLogCollectStrategy
from .zte import ZteLogCollectStrategy

# --- Auto-register all vendor strategies ---
LogCollectStrategyRegistry.register("generic", GenericLogCollectStrategy())
LogCollectStrategyRegistry.register("xfusion", XFusionLogCollectStrategy())
LogCollectStrategyRegistry.register("lenovo", LenovoLogCollectStrategy())
LogCollectStrategyRegistry.register("inspur", InspurLogCollectStrategy())
LogCollectStrategyRegistry.register("nettrix", NettrixLogCollectStrategy())
LogCollectStrategyRegistry.register("zte", ZteLogCollectStrategy())

__all__ = [
    "BaseLogCollectStrategy",
    "GenericLogCollectStrategy",
    "XFusionLogCollectStrategy",
    "LenovoLogCollectStrategy",
    "InspurLogCollectStrategy",
    "NettrixLogCollectStrategy",
    "ZteLogCollectStrategy",
    "LogCollectStrategyRegistry",
    "VendorDetector",
]
