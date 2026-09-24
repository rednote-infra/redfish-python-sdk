"""
Enginetech (安擎) firmware update strategy.

Enginetech BMCs use the Oem.Public extension to distinguish the firmware type
being flashed (BMC / BIOS / CPLD, etc.) and to carry file-server
credentials plus config-preservation flags in the SimpleUpdate body.

Reference: UpdateService固件刷新接口 — 安擎 (Enginetech)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.common import RedfishResponse
from .base import BaseUpdateStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)


class EnginetechUpdateStrategy(BaseUpdateStrategy):
    """
    Firmware update strategy for Enginetech (安擎) servers.

    Supported kwargs:
        image_type (str): Firmware type -> Oem.Public.ImageType
                          (e.g. "BMC", "BIOS", "HPM")
        username (str): File server username -> body.Username
        password (str): File server password -> body.Password
        preserve_config (bool): Preserve config -> Oem.Public.PreserveConf
    """

    def execute(
        self,
        client: RedfishClient,
        image_uri: str,
        transfer_protocol: str = "HTTP",
        targets: Optional[list] = None,
        **kwargs: Any,
    ) -> RedfishResponse:
        target = self._discover_action_target(client)

        body: Dict[str, Any] = {
            "ImageURI": image_uri,
            "TransferProtocol": transfer_protocol,
        }

        # targets 必须由调用方显式配置，禁止在策略内部自动推导，
        # 避免刷错固件目标。未提供时直接报错提示。
        if not targets:
            raise ValueError(
                "EnginetechUpdateStrategy: 'targets' 必须显式配置"
                "（例如 --targets /redfish/v1/UpdateService/FirmwareInventory/BMCImage1），"
                "不允许使用策略自动推导的默认值。"
            )
        body["Targets"] = targets

        # File server credentials
        if kwargs.get("username"):
            body["Username"] = kwargs["username"]
        if kwargs.get("password"):
            body["Password"] = kwargs["password"]

        # Build OEM extension
        oem_public: Dict[str, Any] = {}

        if kwargs.get("image_type"):
            oem_public["ImageType"] = kwargs["image_type"]
        if "preserve_config" in kwargs:
            oem_public["PreserveConf"] = bool(kwargs["preserve_config"])

        if oem_public:
            body["Oem"] = {"Public": oem_public}

        logger.info(
            "EnginetechUpdateStrategy: triggering SimpleUpdate with ImageURI=%s, "
            "ImageType=%s",
            image_uri,
            kwargs.get("image_type"),
        )
        return client._http_client.post(target, RedfishResponse, raw_body=body)
