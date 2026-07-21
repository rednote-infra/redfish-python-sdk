"""
xFusion (超聚变) firmware update strategy.

xFusion BMCs place extension fields at the body top level (not under Oem),
including PreserveConfig, ActiveMode, and ModuleArray for PSU updates.

Reference: UpdateService固件刷新接口 — 超聚变
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.common import RedfishResponse
from .base import BaseUpdateStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)


class XFusionUpdateStrategy(BaseUpdateStrategy):
    """
    Firmware update strategy for xFusion (超聚变) servers.

    Supported kwargs:
        preserve_config (bool): Preserve config -> body.PreserveConfig
        active_mode (str): Immediately/ResetBMC -> body.ActiveMode
        module_array (list): PSU module names -> body.ModuleArray
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

        # xFusion puts extension fields at body top level
        if "preserve_config" in kwargs:
            body["PreserveConfig"] = bool(kwargs["preserve_config"])
        if kwargs.get("active_mode"):
            body["ActiveMode"] = kwargs["active_mode"]
        if kwargs.get("module_array"):
            body["ModuleArray"] = kwargs["module_array"]

        logger.info(
            "XFusionUpdateStrategy: triggering SimpleUpdate with ImageURI=%s",
            image_uri,
        )
        return client._http_client.post(target, RedfishResponse, raw_body=body)
