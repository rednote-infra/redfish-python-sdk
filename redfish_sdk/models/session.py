"""
Session service models.

"""
from __future__ import annotations

from typing import Optional

from pydantic import Field

from .common import Entity, Link, Status
from .oem import Oem


class SessionService(Entity):
    """
    The Session service manages client sessions.
    Endpoint: /redfish/v1/SessionService
    """
    sessions: Optional[Link] = Field(None, alias="Sessions")
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    session_timeout: Optional[int] = Field(None, alias="SessionTimeout")
    status: Optional[Status] = Field(None, alias="Status")


class Session(Entity):
    """
    Represents a single active session between a client and the Redfish service.
    Endpoint: /redfish/v1/SessionService/Sessions/{sessionId}

    After creation, the response contains the X-Auth-Token in the response header
    (not in the JSON body). The SDK automatically extracts and stores this token.

    """
    oem_session_type: Optional[str] = Field(None, alias="OemSessionType")
    password: Optional[str] = Field(None, alias="Password")
    session_type: Optional[str] = Field(None, alias="SessionType")
    user_name: Optional[str] = Field(None, alias="UserName")
    oem: Optional[Oem] = Field(None, alias="Oem")

    # Populated by the SDK after session creation (from X-Auth-Token response header)
    x_auth_token: Optional[str] = Field(None, exclude=True)
