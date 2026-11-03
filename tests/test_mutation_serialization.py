"""Offline coverage for field-presence-aware mutation serialization."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Optional
from unittest.mock import Mock

import pytest
import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from redfish_sdk.http_client import RedfishHttpClient
from redfish_sdk.models.account import Account
from redfish_sdk.models.common import RedfishResponse


class NestedMutation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    clearable: Optional[str] = Field(None, alias="Clearable")
    omitted_default: str = Field("nested-default", alias="OmittedDefault")


class MutationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    clearable: Optional[str] = Field(None, alias="Clearable")
    nested: Optional[NestedMutation] = Field(None, alias="Nested")
    omitted_default: str = Field("top-default", alias="OmittedDefault")
    enabled: Optional[bool] = Field(None, alias="Enabled")
    count: Optional[int] = Field(None, alias="Count")
    text: Optional[str] = Field(None, alias="Text")
    items: Optional[list[str]] = Field(None, alias="Items")
    oem: Optional[dict[str, Any]] = Field(None, alias="Oem")


class NonNullableMutation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    required_value: str = Field(alias="RequiredValue")


def _http() -> RedfishHttpClient:
    return RedfishHttpClient(
        "mock-bmc-host",
        "mock-user",
        "mock-password",
        verify_ssl=True,
    )


def _response(status: HTTPStatus = HTTPStatus.NO_CONTENT) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = b""
    response.request = requests.Request(
        "POST",
        "https://mock-bmc-host/redfish/v1/Oem/Vendor/Mutation",
    ).prepare()
    return response


@pytest.mark.parametrize("method_name", ["post", "patch"])
def test_typed_mutation_preserves_explicit_values_recursively(method_name):
    http = _http()
    send = Mock(return_value=_response())
    http._request = send
    body = MutationRequest(
        clearable=None,
        nested=NestedMutation(clearable=None),
        enabled=False,
        count=0,
        text="",
        items=[],
        oem={},
    )

    getattr(http, method_name)(
        "/redfish/v1/Oem/Vendor/Mutation",
        RedfishResponse,
        body=body,
    )

    assert send.call_args.kwargs["json"] == {
        "Clearable": None,
        "Nested": {"Clearable": None},
        "Enabled": False,
        "Count": 0,
        "Text": "",
        "Items": [],
        "Oem": {},
    }
    http.close()


@pytest.mark.parametrize("method_name", ["post", "patch"])
def test_typed_mutation_omits_unset_defaults(method_name):
    http = _http()
    send = Mock(return_value=_response())
    http._request = send

    getattr(http, method_name)(
        "/redfish/v1/Oem/Vendor/Mutation",
        RedfishResponse,
        body=MutationRequest(),
    )

    assert send.call_args.kwargs["json"] == {}
    http.close()


@pytest.mark.parametrize("method_name", ["post_raw", "patch_raw"])
def test_raw_mutation_payload_is_unchanged(method_name):
    http = _http()
    send = Mock(return_value=_response())
    http._request = send
    payload = {
        "Clearable": None,
        "Enabled": False,
        "Count": 0,
        "Text": "",
        "Items": [],
        "Oem": {},
    }

    getattr(http, method_name)(
        "/redfish/v1/Oem/Vendor/Mutation",
        body=payload,
    )

    assert send.call_args.kwargs["json"] is payload
    http.close()


def test_request_model_can_reject_null_for_non_nullable_field():
    with pytest.raises(ValidationError):
        NonNullableMutation(required_value=None)


def test_model_validate_keeps_absent_response_fields_out_of_patch():
    http = _http()
    send = Mock(return_value=_response())
    http._request = send
    account = Account.model_validate({"UserName": "operator"})

    http.patch(
        "/redfish/v1/AccountService/Accounts/1",
        Account,
        body=account,
    )

    assert send.call_args.kwargs["json"] == {"UserName": "operator"}
    http.close()


def test_user_built_account_preserves_explicit_null_in_patch():
    http = _http()
    send = Mock(return_value=_response())
    http._request = send

    http.patch(
        "/redfish/v1/AccountService/Accounts/1",
        Account,
        body=Account(enabled=None),
    )

    assert send.call_args.kwargs["json"] == {"Enabled": None}
    http.close()
