"""
Base update strategy and generic (standard Redfish) fallback implementation.

All vendor-specific strategies inherit from BaseUpdateStrategy and override
the execute() method to build the vendor-appropriate request body.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...models.common import RedfishResponse

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)


class BaseUpdateStrategy(ABC):
    """
    Abstract base class for firmware update strategies.

    Subclasses must implement execute() to construct the vendor-specific
    request body and POST it to the SimpleUpdate action target.
    """

    def _discover_action_target(self, client: RedfishClient) -> str:
        """
        Discover the SimpleUpdate action target URL from the UpdateService.

        Falls back to the standard path if the target is not found in Actions.
        """
        update_service = client._get_update_service()
        raw = client._http_client.get_raw(update_service.odata_id)
        actions = raw.get("Actions", {})
        simple_update_action = actions.get("#UpdateService.SimpleUpdate", {})
        target = simple_update_action.get("target")

        if not target:
            target = f"{update_service.odata_id}/Actions/UpdateService.SimpleUpdate"

        return target

    @abstractmethod
    def execute(
        self,
        client: RedfishClient,
        image_uri: str,
        transfer_protocol: str = "HTTP",
        targets: Optional[list] = None,
        **kwargs: Any,
    ) -> RedfishResponse:
        """
        Execute the firmware update.

        Args:
            client: RedfishClient instance (provides HTTP access)
            image_uri: URI of the firmware image
            transfer_protocol: Transfer protocol (HTTP, NFS, TFTP, etc.)
            targets: Optional list of firmware target paths
            **kwargs: Vendor-specific parameters

        Returns:
            RedfishResponse (may contain a task reference for async update)
        """
        ...


class GenericUpdateStrategy(BaseUpdateStrategy):
    """
    Standard Redfish SimpleUpdate strategy (fallback).

    Sends the standard body with ImageURI, TransferProtocol, and optional
    Targets. This is equivalent to the original simple_update implementation
    and is used when the vendor is not recognized.
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
        if targets:
            body["Targets"] = targets

        logger.info(
            "GenericUpdateStrategy: triggering SimpleUpdate with ImageURI=%s",
            image_uri,
        )
        return client._http_client.post(target, RedfishResponse, raw_body=body)
