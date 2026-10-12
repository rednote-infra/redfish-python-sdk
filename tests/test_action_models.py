"""Action descriptors and ActionInfo preserve aliases and optional metadata."""

import pytest

from redfish_sdk.models.actions import ActionDescriptor, ActionInfo, ActionMap


def test_action_descriptor_round_trip_preserves_metadata():
    payload = {"target": "/custom/action", "@Redfish.ActionInfo": "/custom/info", "VendorFlag": True}
    action = ActionDescriptor.model_validate(payload)
    assert action.target == "/custom/action"
    assert action.action_info == "/custom/info"
    assert action.model_dump(by_alias=True, exclude_none=True) == payload


@pytest.mark.parametrize("target", [None, 7, [], {}])
def test_invalid_targets_are_unavailable(target):
    assert ActionDescriptor.model_validate({"target": target}).target is None


@pytest.mark.parametrize("values", [[], ["ForceRestart"], None])
def test_action_info_preserves_empty_and_missing_allowable_values(values):
    info = ActionInfo.model_validate({"Parameters": [{"Name": "ResetType", "Required": True, "DataType": "String", "AllowableValues": values}]})
    assert info.parameters[0].name == "ResetType"
    assert info.parameters[0].required is True
    assert info.allowable_values("ResetType") == values
    assert info.allowable_values("OtherParameter") is None


@pytest.mark.parametrize("payload", [{}, {"Parameters": None}, {"Parameters": []}])
def test_action_info_with_no_parameters(payload):
    assert ActionInfo.model_validate(payload).allowable_values("ResetType") is None


def test_action_map_preserves_legacy_oem_dictionary_access():
    actions = ActionMap.model_validate({"#Manager.GeneralDownload": {"target": "/custom/download"}, "Oem": {"Vendor": True}})
    assert actions.get("#Manager.GeneralDownload")["target"] == "/custom/download"
    assert actions.get("Oem") == {"Vendor": True}
    assert actions.get("missing", "fallback") == "fallback"
    assert actions["#Manager.GeneralDownload"]["target"] == "/custom/download"
    with pytest.raises(KeyError):
        actions["missing"]
