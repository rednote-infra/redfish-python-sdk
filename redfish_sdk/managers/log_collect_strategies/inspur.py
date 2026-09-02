"""
Inspur (浪潮) out-of-band log collection strategy.

Inspur BMCs support the standard ``#LogService.CollectDiagnosticData``
action. The one-click collection maps to an OEM diagnostic dump that
bundles system and BMC service data.

Reference: 各厂商 redfish 一键采集 — 浪潮
"""
from __future__ import annotations

import logging

from .base import BaseLogCollectStrategy

logger = logging.getLogger(__name__)


class InspurLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for Inspur (浪潮) servers.

    Defaults to an OEM diagnostic dump; the produced bundle is resolved via
    the standard ``AdditionalDataURI``.
    """

    default_diagnostic_data_type = "OEM"
