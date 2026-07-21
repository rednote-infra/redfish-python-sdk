"""
Update service manager — manages firmware updates.

Provides:
- Firmware inventory listing
- Client certificate listing
- Firmware update (SimpleUpdate) with multi-vendor strategy support

"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Optional

from ..models.common import RedfishResponse
from ..models.update import ClientCertificate, FirmwareInventory
from .update_strategies import UpdateStrategyRegistry, VendorDetector

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


class UpdateServiceManager:
    """
    Manages Redfish Update service resources.

    SimpleUpdate automatically detects the server vendor and applies
    the appropriate request body format. Users can override the vendor
    detection by passing the ``vendor`` parameter.
    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def firmware_inventory(self) -> List[FirmwareInventory]:
        """
        Get the list of firmware inventory entries.

        """
        update_service = self._client._get_update_service()
        return self._client._get_collection(
            update_service.firmware_inventory.odata_id, FirmwareInventory
        )

    def client_certificates(self) -> List[ClientCertificate]:
        """
        Get the list of client certificates for firmware update authentication.

        """
        update_service = self._client._get_update_service()
        return self._client._get_collection(
            update_service.client_certificates.odata_id, ClientCertificate
        )

    def simple_update(
        self,
        image_uri: str,
        transfer_protocol: str = "HTTP",
        targets: Optional[list] = None,
        vendor: Optional[str] = None,
        **kwargs: Any,
    ) -> RedfishResponse:
        """
        Trigger a firmware update via a remote image URI (e.g., NFS, HTTP).

        Automatically detects the server vendor and uses the appropriate
        request body format. The vendor can be manually overridden.

        Args:
            image_uri: URI of the firmware image (e.g., "http://nas/fw/bmc.bin")
            transfer_protocol: Transfer protocol (e.g., "HTTP", "NFS", "TFTP")
            targets: Optional list of firmware target paths
                     (e.g., ["/redfish/v1/Managers/1"] or ["ActiveBMC"])
            vendor: Optional vendor override (e.g., "inspur", "lenovo").
                    If not set, the vendor is auto-detected.
            **kwargs: Vendor-specific parameters. Common ones include:
                - username (str): File server username (Inspur, Lenovo, H3C)
                - password (str): File server password (Inspur, Lenovo, H3C)
                - preserve_config (bool): Preserve configuration during update

        Returns:
            RedfishResponse (may contain a task reference for async update)
        """
        detected_vendor = vendor or VendorDetector.detect(self._client)
        strategy = UpdateStrategyRegistry.get(detected_vendor)

        logger.info(
            "SimpleUpdate: vendor=%s, strategy=%s, ImageURI=%s",
            detected_vendor,
            type(strategy).__name__,
            image_uri,
        )

        return strategy.execute(
            self._client, image_uri, transfer_protocol, targets, **kwargs
        )
