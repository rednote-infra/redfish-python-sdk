"""
Nettrix (宁畅) firmware update strategy.

Nettrix BMCs are closest to standard Redfish. The only extension is
SaveConfig at the body top level (not under Oem).

Reference: UpdateService固件刷新接口 — 宁畅
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.common import RedfishResponse
from .base import BaseUpdateStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)


class NettrixUpdateStrategy(BaseUpdateStrategy):
    """
    Firmware update strategy for Nettrix (宁畅) servers.

    Supported kwargs:
        preserve_config (bool): Preserve config -> body.SaveConfig
    """

    def execute(
        self,
        client: RedfishClient,
        image_uri: str,
        transfer_protocol: str = "HTTPS",
        targets: Optional[list] = None,
        **kwargs: Any,
    ) -> RedfishResponse:
        target = self._discover_action_target(client)

        body: Dict[str, Any] = {
            "ImageURI": image_uri,
            "TransferProtocol": transfer_protocol,
        }
        if targets:
            body["Targets"] = targets

        # Nettrix puts SaveConfig at the body top level
        if "preserve_config" in kwargs:
            body["SaveConfig"] = bool(kwargs["preserve_config"])

        logger.info(
            "NettrixUpdateStrategy: triggering SimpleUpdate with ImageURI=%s",
            image_uri,
        )
        return client._http_client.post(target, RedfishResponse, raw_body=body)
