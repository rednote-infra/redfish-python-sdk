"""
Registry models.

"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

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
    registry_prefix: Optional[str] = Field(
        None,
        alias="RegistryPrefix",
        validation_alias=AliasChoices("RegistryPrefix", "Registry"),
    )
    registry_version: Optional[str] = Field(None, alias="RegistryVersion")


class RegistryLocation(Entity):
    """Location info for a registry file."""
    archive_file: Optional[str] = Field(None, alias="ArchiveFile")
    archive_uri: Optional[str] = Field(None, alias="ArchiveUri")
    language: Optional[str] = Field(None, alias="Language")
    publication_uri: Optional[str] = Field(None, alias="PublicationUri")
    uri: Optional[str] = Field(None, alias="Uri")


class RegistryMessage(BaseModel):
    """A message definition contained in a Redfish message registry document."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    description: Optional[str] = Field(None, alias="Description")
    message: Optional[str] = Field(None, alias="Message")
    message_severity: Optional[str] = Field(
        None,
        alias="MessageSeverity",
        validation_alias=AliasChoices("MessageSeverity", "Severity"),
    )
    number_of_args: Optional[int] = Field(None, alias="NumberOfArgs")
    param_types: Optional[List[str]] = Field(None, alias="ParamTypes")
    resolution: Optional[str] = Field(None, alias="Resolution")
    referenced_registry: Optional[str] = Field(None, alias="ReferencedRegistry")
    version_added: Optional[str] = Field(None, alias="VersionAdded")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class MessageRegistry(Entity):
    """A complete message-registry document loaded from a Registry location.

    This is distinct from :class:`Registry`, which represents the RegistryFile
    resource advertised by ``/redfish/v1/Registries``.  ``ReferencedRegistry``
    is modeled at the document level as specified by MessageRegistry v1.9.0;
    :class:`RegistryMessage` also accepts the per-message representation shown
    in the DMTF 2026.2 overview for interoperability.
    """

    language: Optional[str] = Field(None, alias="Language")
    messages: Dict[str, RegistryMessage] = Field(default_factory=dict, alias="Messages")
    owning_entity: Optional[str] = Field(None, alias="OwningEntity")
    registry_prefix: Optional[str] = Field(None, alias="RegistryPrefix")
    registry_version: Optional[str] = Field(None, alias="RegistryVersion")
    referenced_registry: Optional[str] = Field(None, alias="ReferencedRegistry")
    version_added: Optional[str] = Field(None, alias="VersionAdded")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")


class ResolvedMessage(BaseModel):
    """A registry message resolved and optionally formatted for display."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    requested_message_id: str
    message_id: str
    registry_prefix: str
    registry_version: str
    message_key: str
    message: str
    message_args: List[str] = Field(default_factory=list)
    message_severity: Optional[str] = None
    resolution: Optional[str] = None
