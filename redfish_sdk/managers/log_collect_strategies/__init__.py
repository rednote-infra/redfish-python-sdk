"""
Log-collect strategies for multi-vendor out-of-band diagnostic log support.

This package implements the Strategy Pattern for
``#LogService.CollectDiagnosticData``, allowing a vendor to customise the
request body and artifact resolution while keeping a single entry point in
``ManagersManager.collect_diagnostic_data()``.

Architecture:
    BaseLogCollectStrategy (ABC)
      ├── GenericLogCollectStrategy       — standard Redfish (DMTF) default
      ├── XFusionLogCollectStrategy       — xFusion (超聚变), OEM diagnostic body
      ├── InspurLogCollectStrategy        — Inspur (浪潮), collection-level
                                            CollectAllLog / DownloadAllLog pair
      ├── LenovoLogCollectStrategy        — Lenovo (联想, AMI-based),
                                            CollectAllLog + private
                                            CollectProgress + DownloadAllLog
      ├── ZteLogCollectStrategy           — ZTE (中兴), Dump + Dump/Progress +
                                            GeneralDownload
      └── SmoothcomputeLogCollectStrategy — smoothcompute (顺算), OEM
                                            DiagnosticService.CollectBlackBox /
                                            ExportBlackBox (trigger returns a
                                            standard Task, so waiting reuses
                                            the base TaskService flow)

Only vendors that genuinely differ from the standard DMTF behaviour get a
dedicated strategy. Vendors whose ``CollectDiagnosticData`` matches the
standard body (e.g. Lenovo, Nettrix) intentionally have no file and fall back
to :class:`GenericLogCollectStrategy` via the registry.

Vendor detection is shared with the firmware ``update_strategies`` package
via :class:`VendorDetector`.

All strategies are auto-registered when this package is imported.
"""

from ..update_strategies.vendor_detect import VendorDetector
from .base import BaseLogCollectStrategy, GenericLogCollectStrategy
from .inspur import InspurLogCollectStrategy
from .lenovo import LenovoLogCollectStrategy
from .registry import LogCollectStrategyRegistry
from .smoothcompute import SmoothcomputeLogCollectStrategy
from .xfusion import XFusionLogCollectStrategy
from .zte import ZteLogCollectStrategy

# --- Auto-register vendor strategies that differ from the DMTF default ---
LogCollectStrategyRegistry.register("generic", GenericLogCollectStrategy())
LogCollectStrategyRegistry.register("xfusion", XFusionLogCollectStrategy())
LogCollectStrategyRegistry.register("inspur", InspurLogCollectStrategy())
LogCollectStrategyRegistry.register("lenovo", LenovoLogCollectStrategy())
LogCollectStrategyRegistry.register("zte", ZteLogCollectStrategy())
LogCollectStrategyRegistry.register(
    "smoothcompute", SmoothcomputeLogCollectStrategy()
)

__all__ = [
    "BaseLogCollectStrategy",
    "GenericLogCollectStrategy",
    "XFusionLogCollectStrategy",
    "InspurLogCollectStrategy",
    "LenovoLogCollectStrategy",
    "ZteLogCollectStrategy",
    "SmoothcomputeLogCollectStrategy",
    "LogCollectStrategyRegistry",
    "VendorDetector",
]
