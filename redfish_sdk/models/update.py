"""
Update service models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from .common import Entity, Link, Status


class UpdateService(Entity):
    """
    The Update service provides firmware update capabilities.
    Endpoint: /redfish/v1/UpdateService
    """
    firmware_inventory: Optional[Link] = Field(None, alias="FirmwareInventory")
    software_inventory: Optional[Link] = Field(None, alias="SoftwareInventory")
    client_certificates: Optional[Link] = Field(None, alias="ClientCertificates")
    http_push_uri: Optional[str] = Field(None, alias="HttpPushUri")
    multi_part_http_push_uri: Optional[str] = Field(None, alias="MultiPartHttpPushUri")
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    status: Optional[Status] = Field(None, alias="Status")


class FirmwareInventory(Entity):
    """
    Represents a firmware component in the inventory.
    Endpoint: /redfish/v1/UpdateService/FirmwareInventory/{inventoryId}

    """
    description: Optional[str] = Field(None, alias="Description")
    lowest_supported_version: Optional[str] = Field(None, alias="LowestSupportedVersion")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")
    related_item: Optional[List[Link]] = Field(None, alias="RelatedItem")
    release_date: Optional[str] = Field(None, alias="ReleaseDate")
    software_id: Optional[str] = Field(None, alias="SoftwareId")
    status: Optional[Status] = Field(None, alias="Status")
    updateable: Optional[bool] = Field(None, alias="Updateable")
    version: Optional[str] = Field(None, alias="Version")


class ClientCertificate(Entity):
    """
    Represents a client certificate for firmware update authentication.
    Endpoint: /redfish/v1/UpdateService/ClientCertificates/{certId}
    """
    certificate_string: Optional[str] = Field(None, alias="CertificateString")
    certificate_type: Optional[str] = Field(None, alias="CertificateType")
    issuer: Optional[dict] = Field(None, alias="Issuer")
    subject: Optional[dict] = Field(None, alias="Subject")
    valid_not_after: Optional[str] = Field(None, alias="ValidNotAfter")
    valid_not_before: Optional[str] = Field(None, alias="ValidNotBefore")
