"""
Lenovo (联想) firmware update strategy.

Lenovo BMCs are closest to standard Redfish with no OEM extensions.
The only addition is optional Username/Password for file server auth.

Reference: UpdateService固件刷新接口 — 联想
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.common import RedfishResponse
from .base import BaseUpdateStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)


class LenovoUpdateStrategy(BaseUpdateStrategy):
    """
    Firmware update strategy for Lenovo (联想) servers.

    Supported kwargs:
        username (str): File server username -> body.Username
        password (str): File server password -> body.Password
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

        # Lenovo supports file server credentials
        if kwargs.get("username"):
            body["Username"] = kwargs["username"]
        if kwargs.get("password"):
            body["Password"] = kwargs["password"]

        logger.info(
            "LenovoUpdateStrategy: triggering SimpleUpdate with ImageURI=%s",
            image_uri,
        )
        return client._http_client.post(target, RedfishResponse, raw_body=body)
