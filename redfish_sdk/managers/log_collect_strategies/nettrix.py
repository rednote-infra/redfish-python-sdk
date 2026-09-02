"""
Nettrix (宁畅) out-of-band log collection strategy.

Nettrix BMCs expose the standard ``#LogService.CollectDiagnosticData``
action. The one-click collection maps to a ``Manager`` diagnostic dump.

Reference: 各厂商 redfish 一键采集 — 宁畅
"""
from __future__ import annotations

import logging

from .base import BaseLogCollectStrategy

logger = logging.getLogger(__name__)


class NettrixLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for Nettrix (宁畅) servers.

    Uses the standard DMTF body with a ``Manager`` default.
    """

    default_diagnostic_data_type = "Manager"
