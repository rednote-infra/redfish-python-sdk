"""
ZTE (中兴) out-of-band log collection strategy.

ZTE BMCs expose the standard ``#LogService.CollectDiagnosticData`` action.
The one-click collection maps to an OEM diagnostic dump.

Reference: 各厂商 redfish 一键采集 — 中兴
"""
from __future__ import annotations

import logging

from .base import BaseLogCollectStrategy

logger = logging.getLogger(__name__)


class ZteLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for ZTE (中兴) servers.

    Defaults to an OEM diagnostic dump; the produced bundle is resolved via
    the standard ``AdditionalDataURI``.
    """

    default_diagnostic_data_type = "OEM"
