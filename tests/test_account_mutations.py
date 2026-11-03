"""Writable account request models and legacy compatibility coverage."""

import logging
from unittest.mock import MagicMock

import pytest
import requests
from pydantic import ValidationError

from redfish_sdk.http_client import RedfishHttpClient
from redfish_sdk.managers.account import AccountServiceManager
from redfish_sdk.models.account import (
    Account,
    AccountCreate,
    AccountPatch,
    AccountService,
    AccountSNMP,
)
from redfish_sdk.models.common import Link


def _manager():
    client = MagicMock()
    client._http_client = MagicMock()
    client._get_account_service.return_value = AccountService(
        accounts=Link(odata_id="/redfish/v1/AccountService/Accounts")
    )
    return AccountServiceManager(client), client._http_client


@pytest.mark.parametrize("missing", ["UserName", "Password", "RoleId"])
def test_account_create_requires_dmtf_create_fields(missing):
    payload = {
        "UserName": "operator",
        "Password": "initial-password",
        "RoleId": "Operator",
    }
    del payload[missing]

    with pytest.raises(ValidationError):
        AccountCreate.model_validate(payload)


@pytest.mark.parametrize(
    "read_only",
    [
        {"@odata.id": "/redfish/v1/AccountService/Accounts/1"},
        {"@odata.type": "#ManagerAccount.v1_14_0.ManagerAccount"},
        {"@odata.etag": 'W/"account"'},
        {"Id": "1"},
        {"Name": "Operator account"},
        {"Status": {"State": "Enabled"}},
        {"Certificates": {"@odata.id": "/certificates"}},
        {"Actions": {}},
        {"VendorResponseField": True},
    ],
)
def test_account_patch_rejects_response_and_unknown_fields(read_only):
    with pytest.raises(ValidationError):
        AccountPatch.model_validate(read_only)


def test_account_requests_keep_secrets_out_of_repr_and_allow_oem_container():
    request = AccountCreate(
        user_name="operator",
        password="initial-password",
        role_id="Operator",
        snmp=AccountSNMP(
            authentication_key="authentication-secret",
            encryption_key="encryption-secret",
        ),
        oem={"Vendor": {"WritableSetting": True}},
    )

    rendered = repr(request)
    assert "initial-password" not in rendered
    assert "authentication-secret" not in rendered
    assert "encryption-secret" not in rendered
    assert request.model_dump(by_alias=True, exclude_unset=True)["Oem"] == {
        "Vendor": {"WritableSetting": True}
    }
    with pytest.raises(ValidationError):
        AccountPatch.model_validate({"Vendor": {"WritableSetting": True}})


def test_account_request_secrets_are_redacted_from_http_logs(caplog):
    response = requests.Response()
    response.status_code = 204
    response._content = b""
    response.request = requests.Request(
        "POST", "https://mock-bmc/redfish/v1/AccountService/Accounts"
    ).prepare()
    http = RedfishHttpClient(
        "mock-bmc", "mock-user", "mock-password", verify_ssl=True
    )
    http._request = MagicMock(return_value=response)
    request = AccountCreate(
        user_name="operator",
        password="initial-password",
        role_id="Operator",
        snmp=AccountSNMP(
            authentication_key="authentication-secret",
            encryption_key="encryption-secret",
        ),
    )

    with caplog.at_level(logging.INFO):
        http.post(
            "/redfish/v1/AccountService/Accounts",
            Account,
            body=request,
        )

    assert "initial-password" not in caplog.text
    assert "authentication-secret" not in caplog.text
    assert "encryption-secret" not in caplog.text
    http.close()


def test_account_patch_preserves_explicit_null_and_omits_unset_fields():
    request = AccountPatch(email_address=None, enabled=False)

    assert request.model_dump(by_alias=True, exclude_unset=True) == {
        "EmailAddress": None,
        "Enabled": False,
    }


def test_manager_uses_dedicated_request_models_directly():
    manager, http = _manager()
    create = AccountCreate(
        user_name="operator",
        password="initial-password",
        role_id="Operator",
    )
    patch = AccountPatch(enabled=False)
    current = Account(user_name="operator", odata_id="/accounts/operator")
    manager.accounts = MagicMock(return_value=[current])

    manager.add(create)
    manager.update("operator", patch)

    assert http.post.call_args.kwargs["body"] is create
    assert http.patch.call_args.args[2] is patch


def test_legacy_account_create_remains_accepted_and_filters_read_only_fields():
    manager, http = _manager()
    legacy = Account.model_validate({
        "@odata.id": "/accounts/operator",
        "Id": "1",
        "Name": "Operator account",
        "UserName": "operator",
        "Password": "initial-password",
        "RoleId": "Operator",
        "VendorResponseField": True,
    })

    manager.add(legacy)

    body = http.post.call_args.kwargs["body"]
    assert isinstance(body, AccountCreate)
    assert body.model_dump(by_alias=True, exclude_unset=True) == {
        "Password": "initial-password",
        "RoleId": "Operator",
        "UserName": "operator",
    }


def test_legacy_incomplete_account_create_keeps_server_validation_compatibility():
    manager, http = _manager()

    manager.add(Account(user_name="legacy-user"))

    body = http.post.call_args.kwargs["body"]
    assert isinstance(body, AccountCreate)
    assert body.model_dump(by_alias=True, exclude_unset=True) == {
        "UserName": "legacy-user"
    }


def test_fetched_account_update_filters_response_data_and_response_password_null():
    manager, http = _manager()
    fetched = Account.model_validate({
        "@odata.id": "/accounts/operator",
        "@odata.type": "#ManagerAccount.v1_14_0.ManagerAccount",
        "@odata.etag": 'W/"account"',
        "Id": "1",
        "Name": "Operator account",
        "Status": {"State": "Enabled"},
        "Certificates": {"@odata.id": "/certificates"},
        "Actions": {},
        "UserName": "operator",
        "Password": None,
        "RoleId": "Operator",
        "Enabled": True,
        "VendorResponseField": True,
    })
    manager.accounts = MagicMock(return_value=[fetched])

    manager.update("operator", fetched)

    body = http.patch.call_args.args[2]
    assert isinstance(body, AccountPatch)
    assert body.model_dump(by_alias=True, exclude_unset=True) == {
        "Enabled": True,
        "RoleId": "Operator",
        "UserName": "operator",
    }


def test_legacy_user_constructed_account_keeps_explicit_null_semantics():
    manager, http = _manager()
    current = Account(user_name="operator", odata_id="/accounts/operator")
    manager.accounts = MagicMock(return_value=[current])

    manager.update("operator", Account(email_address=None))

    body = http.patch.call_args.args[2]
    assert body.model_dump(by_alias=True, exclude_unset=True) == {
        "EmailAddress": None
    }
