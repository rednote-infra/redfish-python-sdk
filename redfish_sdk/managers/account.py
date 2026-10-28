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
from typing import TYPE_CHECKING, List

from ..models.account import Account, Role
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


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

    def add(self, account: Account) -> Account:
        """
        Create a new user account.


        Args:
            account: Account model with UserName, Password, RoleId, Enabled fields

        Returns:
            Created account resource
        """
        account_service = self._client._get_account_service()
        return self._http.post(
            account_service.accounts.odata_id, Account, body=account
        )

    def update(self, username: str, account: Account) -> Account:
        """
        Update an existing user account.


        Args:
            username: Username of the account to update
            account: Account model with fields to update

        Returns:
            Updated account resource
        """
        current = select_member(
            self.accounts(), username, aliases=("user_name",)
        )
        return self._http.patch(current.odata_id, Account, account)

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
