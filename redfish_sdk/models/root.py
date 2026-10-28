"""
Root service model.

"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link
from .oem import Oem


class ProtocolFeaturesSupported(BaseModel):
    """Optional protocol capabilities advertised by the service root."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    alias: Optional[bool] = Field(None, alias="Alias")
    client_context_query: Optional[bool] = Field(None, alias="ClientContextQuery")
    excerpt_query: Optional[bool] = Field(None, alias="ExcerptQuery")
    filter_query: Optional[bool] = Field(None, alias="FilterQuery")
    multiple_http_requests: Optional[bool] = Field(
        None, alias="MultipleHTTPRequests"
    )
    only_member_query: Optional[bool] = Field(None, alias="OnlyMemberQuery")
    select_query: Optional[bool] = Field(None, alias="SelectQuery")
    top_skip_query: Optional[bool] = Field(None, alias="TopSkipQuery")


class RootService(Entity):
    """
    The root Redfish service endpoint (/redfish/v1/).
    Acts as the entry point and service index — contains links to all top-level resources.

    """
    redfish_version: Optional[str] = Field(None, alias="RedfishVersion")
    vendor: Optional[str] = Field(None, alias="Vendor")
    product: Optional[str] = Field(None, alias="Product")
    uuid: Optional[str] = Field(None, alias="UUID")
    protocol_features_supported: Optional[ProtocolFeaturesSupported] = Field(
        None, alias="ProtocolFeaturesSupported"
    )

    # Top-level resource links
    account_service: Optional[Link] = Field(None, alias="AccountService")
    composition_service: Optional[Link] = Field(None, alias="CompositionService")
    task_service: Optional[Link] = Field(None, alias="TaskService")
    telemetry_service: Optional[Link] = Field(None, alias="TelemetryService")
    certificate_service: Optional[Link] = Field(None, alias="CertificateService")
    chassis: Optional[Link] = Field(None, alias="Chassis")
    component_integrity: Optional[Link] = Field(None, alias="ComponentIntegrity")
    event_service: Optional[Link] = Field(None, alias="EventService")
    session_service: Optional[Link] = Field(None, alias="SessionService")
    tasks: Optional[Link] = Field(None, alias="Tasks")
    systems: Optional[Link] = Field(None, alias="Systems")
    update_service: Optional[Link] = Field(None, alias="UpdateService")
    key_service: Optional[Link] = Field(None, alias="KeyService")
    managers: Optional[Link] = Field(None, alias="Managers")
    registries: Optional[Link] = Field(None, alias="Registries")
    json_schemas: Optional[Link] = Field(None, alias="JsonSchemas")

    # Links section (contains Sessions link)
    links: Optional[RootLinks] = Field(None, alias="Links")

    oem: Optional[Oem] = Field(None, alias="Oem")


class RootLinks(Entity):
    """Links section within RootService, contains the Sessions direct link."""
    sessions: Optional[Link] = Field(None, alias="Sessions")
