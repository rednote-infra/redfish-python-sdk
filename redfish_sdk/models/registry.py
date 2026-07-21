"""
Registry models.

"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from .common import Entity


class Registry(Entity):
    """
    Represents a Redfish message registry.
    Endpoint: /redfish/v1/Registries/{registryId}

    Message registries contain descriptions of all possible messages the BMC may generate.
    """
    languages: Optional[List[str]] = Field(None, alias="Languages")
    location: Optional[List[RegistryLocation]] = Field(None, alias="Location")
    owning_entity: Optional[str] = Field(None, alias="OwningEntity")
    registry_prefix: Optional[str] = Field(None, alias="RegistryPrefix")
    registry_version: Optional[str] = Field(None, alias="RegistryVersion")


class RegistryLocation(Entity):
    """Location info for a registry file."""
    archive_file: Optional[str] = Field(None, alias="ArchiveFile")
    archive_uri: Optional[str] = Field(None, alias="ArchiveUri")
    language: Optional[str] = Field(None, alias="Language")
    publication_uri: Optional[str] = Field(None, alias="PublicationUri")
    uri: Optional[str] = Field(None, alias="Uri")
