"""
Account service models.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link, Status
from .oem import Oem


class Authentication(BaseModel):
    """Configured-state flags for external-provider credentials.

    Secret and vendor-specific properties remain untyped extras so this model
    does not alter their accepted values or serialization behavior.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    password_set: Optional[bool] = Field(None, alias="PasswordSet")
    token_set: Optional[bool] = Field(None, alias="TokenSet")
    kerberos_keytab_set: Optional[bool] = Field(None, alias="KerberosKeytabSet")


class ExternalAccountProvider(Entity):
    """An embedded or standalone external account-provider configuration."""

    authentication: Optional[Authentication] = Field(None, alias="Authentication")
    # AccountService kept this provider-level indicator before the configured
    # state fields were added to the nested Authentication object.
    password_set: Optional[bool] = Field(None, alias="PasswordSet")


class AccountService(Entity):
    """
    The Account service provides user account management.
    Endpoint: /redfish/v1/AccountService
    """
    accounts: Optional[Link] = Field(None, alias="Accounts")
    roles: Optional[Link] = Field(None, alias="Roles")
    active_directory: Optional[ExternalAccountProvider] = Field(
        None, alias="ActiveDirectory"
    )
    ldap: Optional[ExternalAccountProvider] = Field(None, alias="LDAP")
    oauth2: Optional[ExternalAccountProvider] = Field(None, alias="OAuth2")
    tacacsplus: Optional[ExternalAccountProvider] = Field(None, alias="TACACSplus")
    additional_external_account_providers: Optional[Link] = Field(
        None, alias="AdditionalExternalAccountProviders"
    )
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
    Represents a user account returned by the BMC.
    Endpoint: /redfish/v1/AccountService/Accounts/{accountId}

    Use :class:`AccountCreate` and :class:`AccountPatch` for new mutation code.
    The client still accepts this response model as a filtered compatibility
    input for existing callers.

    """
    account_types: Optional[List[str]] = Field(None, alias="AccountTypes")
    certificates: Optional[Link] = Field(None, alias="Certificates")
    email_address: Optional[str] = Field(None, alias="EmailAddress")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    locked: Optional[bool] = Field(None, alias="Locked")
    password: Optional[str] = Field(None, alias="Password", repr=False)
    password_change_required: Optional[bool] = Field(None, alias="PasswordChangeRequired")
    phone_number: Optional[str] = Field(None, alias="PhoneNumber")
    role_id: Optional[str] = Field(None, alias="RoleId")
    user_name: Optional[str] = Field(None, alias="UserName")
    oem: Optional[Oem] = Field(None, alias="Oem")


class AccountSNMP(BaseModel):
    """Writable SNMPv3 settings for a manager account."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    authentication_key: Optional[str] = Field(
        None, alias="AuthenticationKey", repr=False
    )
    authentication_protocol: Optional[str] = Field(
        None, alias="AuthenticationProtocol"
    )
    encryption_key: Optional[str] = Field(
        None, alias="EncryptionKey", repr=False
    )
    encryption_protocol: Optional[str] = Field(
        None, alias="EncryptionProtocol"
    )


class _AccountMutation(BaseModel):
    """Writable ManagerAccount properties shared by create and patch."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    account_expiration: Optional[str] = Field(None, alias="AccountExpiration")
    account_types: Optional[List[str]] = Field(None, alias="AccountTypes")
    email_address: Optional[str] = Field(None, alias="EmailAddress")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    locked: Optional[bool] = Field(None, alias="Locked")
    oem_account_types: Optional[List[str]] = Field(None, alias="OEMAccountTypes")
    oem: Optional[Dict[str, Any]] = Field(None, alias="Oem")
    one_time_passcode_delivery_address: Optional[str] = Field(
        None, alias="OneTimePasscodeDeliveryAddress"
    )
    password: Optional[str] = Field(None, alias="Password", repr=False)
    password_change_required: Optional[bool] = Field(
        None, alias="PasswordChangeRequired"
    )
    password_expiration: Optional[str] = Field(None, alias="PasswordExpiration")
    phone_number: Optional[str] = Field(None, alias="PhoneNumber")
    role_id: Optional[str] = Field(None, alias="RoleId")
    snmp: Optional[AccountSNMP] = Field(None, alias="SNMP", repr=False)
    strict_account_types: Optional[bool] = Field(
        None, alias="StrictAccountTypes"
    )
    user_name: Optional[str] = Field(None, alias="UserName")


class AccountCreate(_AccountMutation):
    """Strict writable request for creating a manager account.

    The DMTF-required create properties must be present.  ``Password`` is
    nullable in the schema but remains required as a field.
    """

    password: Optional[str] = Field(alias="Password", repr=False)
    role_id: str = Field(alias="RoleId")
    user_name: str = Field(alias="UserName")


class AccountPatch(_AccountMutation):
    """Strict partial request for updating writable manager-account fields."""


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
