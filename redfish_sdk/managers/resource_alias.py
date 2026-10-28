"""Capability-aware resource alias operations."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Type, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from ..exceptions import RedfishNotFoundError, RedfishValidationError
from ..models.common import Entity

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)

ResourceEntity = TypeVar("ResourceEntity", bound=Entity)
_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class ResourceAliasPatch(BaseModel):
    """PATCH body for the ``@Redfish.Alias`` annotation."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    redfish_alias: str = Field(alias="@Redfish.Alias")


class ResourceAliasManager:
    """Assign, clear, and address user-defined Redfish resource aliases."""

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def _require_capability(self) -> None:
        features = self._client._get_root().protocol_features_supported
        if features is None or features.alias is not True:
            raise RedfishValidationError(
                "The Redfish service does not advertise "
                "ProtocolFeaturesSupported.Alias"
            )

    @staticmethod
    def _validate_alias(alias: str, *, allow_empty: bool = False) -> None:
        if allow_empty and alias == "":
            return
        if not isinstance(alias, str) or not _ALIAS_PATTERN.fullmatch(alias):
            raise RedfishValidationError(
                "Invalid resource alias: use only ASCII letters, digits, '.', "
                "'_', or '-'; '~', reserved characters, whitespace, and "
                "percent-encoded values are not allowed"
            )

    def alias_uri(self, collection_uri: str, alias: str) -> str:
        """Build a same-origin collection-member URI using ``~alias``."""
        self._validate_alias(alias)
        self._require_capability()
        collection_path = self._client._collection_path(collection_uri, "/")
        parts = urlsplit(collection_path)
        if parts.query or parts.fragment:
            raise RedfishValidationError(
                "Alias addressing requires a collection URI without a query or fragment"
            )
        return f"{parts.path.rstrip('/')}/~{alias}"

    def get(
        self,
        collection_uri: str,
        alias: str,
        model_class: Type[ResourceEntity],
    ) -> ResourceEntity:
        """Get a collection member through an alias URI segment."""
        return self._http.get(
            self.alias_uri(collection_uri, alias), model_class
        )

    def set(
        self, resource: ResourceEntity, alias: str
    ) -> ResourceEntity:
        """Assign or clear an alias using the resource's current ETag."""
        self._validate_alias(alias, allow_empty=True)
        self._require_capability()
        if not resource.odata_id:
            raise RedfishNotFoundError(
                f"{type(resource).__name__} does not advertise @odata.id"
            )

        current = resource
        if not current.odata_etag:
            current = self._http.get(resource.odata_id, type(resource))

        headers = {"If-Match": current.odata_etag or "*"}
        body = ResourceAliasPatch(redfish_alias=alias).model_dump(by_alias=True)
        response = self._http.patch_raw(
            resource.odata_id, body, extra_headers=headers
        )

        payload = current.model_dump(by_alias=True, exclude_none=True)
        payload["@Redfish.Alias"] = alias
        if response.text.strip():
            response_payload = response.json()
            if isinstance(response_payload, dict):
                payload.update(response_payload)
        etag = response.headers.get("ETag") or response.headers.get("etag")
        if etag:
            payload["@odata.etag"] = etag

        updated = type(resource).model_validate(payload)
        if any(
            (message.message_id or "").endswith("AliasValueReassigned")
            for message in updated.extended_info or []
        ):
            logger.warning(
                "Resource alias %r was reassigned by the Redfish service",
                alias,
            )
        return updated

    def clear(self, resource: ResourceEntity) -> ResourceEntity:
        """Clear the resource alias with the standard empty-string value."""
        return self.set(resource, "")
