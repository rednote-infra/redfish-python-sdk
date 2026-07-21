"""
Inspur (浪潮) firmware update strategy.

Inspur BMCs use heavy OEM extensions under Oem.Public, including
FlashItem selection, BIOS update type, PFR options, and file server
credentials in the request body.

Reference: UpdateService固件刷新接口 — 浪潮
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.common import RedfishResponse
from .base import BaseUpdateStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)


class InspurUpdateStrategy(BaseUpdateStrategy):
    """
    Firmware update strategy for Inspur (浪潮) servers.

    Supported kwargs:
        username (str): File server username -> body.Username
        password (str): File server password -> body.Password
        preserve_config (bool): Preserve config -> Oem.Public.PreserveConf
        flash_item (str): BMC/BIOS/CPLD -> Oem.Public.FlashItem
        bios_update_type (str): FullBIOS/SeamlessBIOS -> Oem.Public.BIOSUpdateType
        bios_flash (str): Flash1/Flash2/Both -> Oem.Public.BiosFlash
        pfr_type (bool): PFR update toggle -> Oem.Public.PFRType
        pfr_region (str): PFR region -> Oem.Public.PFRRegion
        pfr_update_dynamic (bool): PFR dynamic update -> Oem.Public.PFRUpdateDynamic
        seamless_module (str): BIOS_ONLY/ME/MICROCODE -> Oem.Public.SeamlessModule
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

        # File server credentials
        if kwargs.get("username"):
            body["Username"] = kwargs["username"]
        if kwargs.get("password"):
            body["Password"] = kwargs["password"]

        # Build OEM extension
        oem_public: Dict[str, Any] = {}

        if kwargs.get("flash_item"):
            oem_public["FlashItem"] = kwargs["flash_item"]
        if "preserve_config" in kwargs:
            oem_public["PreserveConf"] = bool(kwargs["preserve_config"])
        if kwargs.get("bios_update_type"):
            oem_public["BIOSUpdateType"] = kwargs["bios_update_type"]
        if kwargs.get("bios_flash"):
            oem_public["BiosFlash"] = kwargs["bios_flash"]
        if "pfr_type" in kwargs:
            oem_public["PFRType"] = bool(kwargs["pfr_type"])
        if kwargs.get("pfr_region"):
            oem_public["PFRRegion"] = kwargs["pfr_region"]
        if "pfr_update_dynamic" in kwargs:
            oem_public["PFRUpdateDynamic"] = bool(kwargs["pfr_update_dynamic"])
        if kwargs.get("seamless_module"):
            oem_public["SeamlessModule"] = kwargs["seamless_module"]

        if oem_public:
            body["Oem"] = {"Public": oem_public}

        logger.info(
            "InspurUpdateStrategy: triggering SimpleUpdate with ImageURI=%s",
            image_uri,
        )
        return client._http_client.post(target, RedfishResponse, raw_body=body)
