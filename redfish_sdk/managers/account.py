"""
Account service manager — manages user accounts and roles.

Provides:
- List accounts
- List roles
- Add account
- Update account
- Delete account

"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Union

from ..models.account import Account, AccountCreate, AccountPatch, Role
from ..models.common import Entity
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)
_PASSWORD_FIELD_NAME = "password"


def _legacy_writable_values(account: Account) -> Dict[str, Any]:
    """Extract writable fields from a legacy response-capable Account model."""
    payload = account.model_dump(by_alias=True, exclude_unset=True)
    values = {
        name: payload[field.alias]
        for name, field in AccountPatch.model_fields.items()
        if field.alias in payload
    }
    if (
        account.model_fields_set.intersection(Entity.model_fields)
        and values.get(_PASSWORD_FIELD_NAME) is None
    ):
        # Redfish returns write-only passwords as null; do not reflect that
        # response placeholder into an update or create request.
        values.pop(_PASSWORD_FIELD_NAME, None)
    return values


class AccountServiceManager:
    """
    Manages Redfish Account resources.

    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def accounts(self) -> List[Account]:
        """
        Get the list of user accounts.

        """
        account_service = self._client._get_account_service()
        return self._client._get_collection(account_service.accounts.odata_id, Account)

    def roles(self) -> List[Role]:
        """
        Get the list of user roles.

        """
        account_service = self._client._get_account_service()
        return self._client._get_collection(account_service.roles.odata_id, Role)

    def add(self, account: Union[AccountCreate, Account]) -> Account:
        """
        Create a new user account.


        Args:
            account: Prefer a strict AccountCreate request.  Account remains
                accepted for backward compatibility; response-only and unknown
                fields are filtered before transmission.

        Returns:
            Created account resource
        """
        account_service = self._client._get_account_service()
        body = (
            account
            if isinstance(account, AccountCreate)
            # Legacy Account callers relied on the BMC to validate missing
            # create fields, so filter their payload without adding a new error.
            else AccountCreate.model_construct(
                **_legacy_writable_values(account)
            )
        )
        return self._http.post(
            account_service.accounts.odata_id, Account, body=body
        )

    def update(
        self, username: str, account: Union[AccountPatch, Account]
    ) -> Account:
        """
        Update an existing user account.


        Args:
            username: Username of the account to update
            account: Prefer a strict AccountPatch request.  Account remains
                accepted for backward compatibility; response-only and unknown
                fields are filtered before transmission.

        Returns:
            Updated account resource
        """
        current = select_member(
            self.accounts(), username, aliases=("user_name",)
        )
        body = (
            account
            if isinstance(account, AccountPatch)
            else AccountPatch.model_validate(
                _legacy_writable_values(account)
            )
        )
        return self._http.patch(current.odata_id, Account, body)

    def delete(self, username: str) -> str:
        """
        Delete a user account.


        Args:
            username: Username of the account to delete

        Returns:
            Response body (usually empty)
        """
        current = select_member(
            self.accounts(), username, aliases=("user_name",)
        )
        return self._http.delete(current.odata_id)
