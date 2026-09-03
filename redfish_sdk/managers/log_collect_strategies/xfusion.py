"""
xFusion (超聚变) out-of-band log collection strategy.

xFusion iBMC exposes the standard ``#LogService.CollectDiagnosticData``
action and produces an OEM diagnostic bundle. The one-click collection maps
to ``DiagnosticDataType == "OEM"`` with ``OEMDiagnosticDataType`` selecting
the full SDS/diagnostic dump.

Reference: 各厂商 redfish 一键采集 — 超聚变
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import BaseLogCollectStrategy

logger = logging.getLogger(__name__)


class XFusionLogCollectStrategy(BaseLogCollectStrategy):
    """
    Log-collect strategy for xFusion (超聚变) servers.

    Defaults to an OEM diagnostic dump. Callers may override the diagnostic
    data type or pass ``oem_params`` for finer control.
    """

    default_diagnostic_data_type = "OEM"

    def build_body(
        self,
        diagnostic_data_type: Optional[str] = None,
        oem_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body = super().build_body(diagnostic_data_type, oem_params)
        # xFusion requires an OEMDiagnosticDataType when the type is OEM.
        if body.get("DiagnosticDataType") == "OEM" and "OEMDiagnosticDataType" not in body:
            body["OEMDiagnosticDataType"] = "Manager"
        logger.info("XFusionLogCollectStrategy: body=%s", body)
        return body
