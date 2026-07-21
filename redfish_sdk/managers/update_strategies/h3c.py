"""
H3C (新华三) firmware update strategy.

H3C BMCs do NOT send a separate TransferProtocol field; the protocol is
embedded in the ImageURI. For SFTP/CIFS, credentials are also embedded
in the URI (e.g., sftp://user:pwd@host/path).

Reference: UpdateService固件刷新接口 — 新华三
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

from ...models.common import RedfishResponse
from .base import BaseUpdateStrategy

if TYPE_CHECKING:
    from ...client import RedfishClient

logger = logging.getLogger(__name__)


class H3cUpdateStrategy(BaseUpdateStrategy):
    """
    Firmware update strategy for H3C (新华三) servers.

    Supported kwargs:
        username (str): File server username -> embedded in ImageURI
        password (str): File server password -> embedded in ImageURI
        preserve_config (bool): True -> "Retain", False -> "Restore"
                                Maps to Oem.Public.Preserve
        restore_mode (str): Retain/Restore/ForceRestore -> Oem.Public.Preserve
                            (overrides preserve_config if both are set)
        reboot_mode (str): Auto/Manual -> Oem.Public.RebootMode
        backup (str): Backup option -> Oem.Public.Backup
        bios_flash (str): Flash1/Flash2/Both -> Oem.Public.BiosFlash
        image_md5_uri (str): MD5 checksum URI -> Oem.Public.ImageMd5URI
        delay (str): Delay duration -> Oem.Public.Date
        upgrade_type (str): all/bios/me/microcode -> Oem.Public.UpgradeType
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

        # H3C embeds credentials in the URI for SFTP/CIFS
        final_uri = self._build_uri_with_credentials(
            image_uri,
            transfer_protocol,
            kwargs.get("username"),
            kwargs.get("password"),
        )

        # H3C does NOT send TransferProtocol as a separate field
        body: Dict[str, Any] = {
            "ImageURI": final_uri,
        }

        # Build OEM extension
        oem_public: Dict[str, Any] = {}

        # Preserve config: restore_mode takes precedence
        if kwargs.get("restore_mode"):
            oem_public["Preserve"] = kwargs["restore_mode"]
        elif "preserve_config" in kwargs:
            oem_public["Preserve"] = "Retain" if kwargs["preserve_config"] else "Restore"

        if kwargs.get("reboot_mode"):
            oem_public["RebootMode"] = kwargs["reboot_mode"]
        if kwargs.get("backup"):
            oem_public["Backup"] = kwargs["backup"]
        if kwargs.get("bios_flash"):
            oem_public["BiosFlash"] = kwargs["bios_flash"]
        if kwargs.get("image_md5_uri"):
            oem_public["ImageMd5URI"] = kwargs["image_md5_uri"]
        if kwargs.get("delay"):
            oem_public["Date"] = kwargs["delay"]
        if kwargs.get("upgrade_type"):
            oem_public["UpgradeType"] = kwargs["upgrade_type"]

        if oem_public:
            body["Oem"] = {"Public": oem_public}

        logger.info(
            "H3cUpdateStrategy: triggering SimpleUpdate with ImageURI=%s",
            final_uri,
        )
        return client._http_client.post(target, RedfishResponse, raw_body=body)

    @staticmethod
    def _build_uri_with_credentials(
        image_uri: str,
        transfer_protocol: str,
        username: Optional[str],
        password: Optional[str],
    ) -> str:
        """
        Embed credentials into the URI for protocols that require it.

        For SFTP/CIFS, H3C expects: sftp://user:pwd@host/path
        For HTTP/TFTP/NFS, credentials are not embedded.
        """
        if not username:
            return image_uri

        proto_lower = transfer_protocol.lower()
        if proto_lower not in ("sftp", "cifs"):
            return image_uri

        parsed = urlparse(image_uri)

        # If credentials are already in the URI, don't override
        if parsed.username:
            return image_uri

        # Build netloc with credentials
        credentials = username
        if password:
            credentials = f"{username}:{password}"

        new_netloc = f"{credentials}@{parsed.hostname}"
        if parsed.port:
            new_netloc = f"{new_netloc}:{parsed.port}"

        return urlunparse((
            parsed.scheme or proto_lower,
            new_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))
