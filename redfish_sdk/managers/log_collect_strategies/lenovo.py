"""
Lenovo (联想) out-of-band log collection strategy.

Lenovo XCC follows standard Redfish closely. Its one-click FFDC/service-data
collection maps to ``DiagnosticDataType == "Manager"`` with the standard
body; the produced bundle is exposed via ``AdditionalDataURI``.

Reference: 各厂商 redfish 一键采集 — 联想
"""
from __future__ import annotations

import logging

from .base import BaseLogCollectStrategy

logger = logging.getLogger(__name__)


class LenovoLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for Lenovo (联想) servers.

    Uses the standard DMTF body with a ``Manager`` default. No OEM fields
    are required; the base implementation resolves ``AdditionalDataURI``.
    """

    default_diagnostic_data_type = "Manager"
