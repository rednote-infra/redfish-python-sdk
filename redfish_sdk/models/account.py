"""
Account service models.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from .common import Entity, Link, Status
from .oem import Oem


class AccountService(Entity):
    """
    The Account service provides user account management.
    Endpoint: /redfish/v1/AccountService
    """
    accounts: Optional[Link] = Field(None, alias="Accounts")
    roles: Optional[Link] = Field(None, alias="Roles")
    auth_failure_logging_threshold: Optional[int] = Field(
        None, alias="AuthFailureLoggingThreshold"
    )
    max_password_length: Optional[int] = Field(None, alias="MaxPasswordLength")
    min_password_length: Optional[int] = Field(None, alias="MinPasswordLength")
    account_lockout_threshold: Optional[int] = Field(None, alias="AccountLockoutThreshold")
    account_lockout_duration: Optional[int] = Field(None, alias="AccountLockoutDuration")
    service_enabled: Optional[bool] = Field(None, alias="ServiceEnabled")
    status: Optional[Status] = Field(None, alias="Status")


class Account(Entity):
    """
    Represents a user account on the BMC.
    Endpoint: /redfish/v1/AccountService/Accounts/{accountId}

    """
    account_types: Optional[List[str]] = Field(None, alias="AccountTypes")
    certificates: Optional[Link] = Field(None, alias="Certificates")
    email_address: Optional[str] = Field(None, alias="EmailAddress")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    locked: Optional[bool] = Field(None, alias="Locked")
    password: Optional[str] = Field(None, alias="Password")
    password_change_required: Optional[bool] = Field(None, alias="PasswordChangeRequired")
    phone_number: Optional[str] = Field(None, alias="PhoneNumber")
    role_id: Optional[str] = Field(None, alias="RoleId")
    user_name: Optional[str] = Field(None, alias="UserName")
    oem: Optional[Oem] = Field(None, alias="Oem")


class Role(Entity):
    """
    Represents an account role with associated privileges.
    Endpoint: /redfish/v1/AccountService/Roles/{roleId}
    """
    assigned_privileges: Optional[List[str]] = Field(None, alias="AssignedPrivileges")
    is_predefined: Optional[bool] = Field(None, alias="IsPredefined")
    oem_privileges: Optional[List[str]] = Field(None, alias="OemPrivileges")
    role_id: Optional[str] = Field(None, alias="RoleId")
    status: Optional[Status] = Field(None, alias="Status")
