"""
ZTE (中兴) firmware update strategy.

ZTE BMCs extend SimpleUpdate with OEM fields under Oem.Public for
BMC/BIOS flash selection, config preservation, and apply time.

Reference: UpdateService固件刷新接口 — 中兴
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.common import RedfishResponse
from .base import BaseUpdateStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)


class ZteUpdateStrategy(BaseUpdateStrategy):
    """
    Firmware update strategy for ZTE (中兴) servers.

    Supported kwargs:
        preserve_config (bool): Preserve config -> Oem.Public.PreserveConf
        bmc_flash (str): Flash1/Flash2/Both -> Oem.Public.BMCFlash
        bios_flash (str): Flash1/Flash2/Both -> Oem.Public.BiosFlash
        apply_time (str): Immediate/OnReset -> Oem.Public.ApplyTime
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

        # Build OEM extension
        oem_public: Dict[str, Any] = {}

        if "preserve_config" in kwargs:
            oem_public["PreserveConf"] = bool(kwargs["preserve_config"])
        if kwargs.get("bmc_flash"):
            oem_public["BMCFlash"] = kwargs["bmc_flash"]
        if kwargs.get("bios_flash"):
            oem_public["BiosFlash"] = kwargs["bios_flash"]
        if kwargs.get("apply_time"):
            oem_public["ApplyTime"] = kwargs["apply_time"]

        if oem_public:
            body["Oem"] = {"Public": oem_public}

        logger.info(
            "ZteUpdateStrategy: triggering SimpleUpdate with ImageURI=%s",
            image_uri,
        )
        return client._http_client.post(target, RedfishResponse, raw_body=body)
