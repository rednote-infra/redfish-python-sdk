"""Typed Attribute Registry discovery and static validation, without a BMC."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from redfish_sdk import RedfishClient, RegistryResolutionError
from redfish_sdk.exceptions import RedfishValidationError
from redfish_sdk.models.registry import MessageRegistry, Registry
from redfish_sdk.models.systems import Bios


def document():
    return json.loads((Path(__file__).parent / "fixtures" / "attribute_registry.json").read_text())


def registry(name="ExampleBios.1.2.0", locations=None):
    return Registry.model_validate({"Id": name, "Registry": name, "Location": locations or [
        {"Language": "en", "Uri": f"/documents/{name}.json"},
    ]})


@pytest.fixture
def client():
    with RedfishClient("example.test", "test", "test", verify_ssl=True) as client:
        client._get_registries_collection = Mock(return_value=[registry()])
        client._http_client.get = Mock(side_effect=lambda path, model: model.model_validate(document()))
        yield client


def test_typed_registry_entries_and_unknown_fields(client):
    result = client.get_attribute_registry("ExampleBios.1.2.0")
    mode = result.get_attribute("Mode")
    assert mode.display_name == "Boot mode" and mode.default_value == "UEFI"
    assert mode.reset_required is True and mode.read_only is False
    assert mode.values[0].value_name == "UEFI"
    assert mode.model_extra["FutureConstraint"]["Example"] is True
    assert result.registry_entries.menus[0].menu_name == "Boot"
    dependency = result.registry_entries.dependencies[0].dependency
    assert dependency.map_from[0].map_from_value is False
    assert dependency.map_to_property == "ReadOnly" and dependency.map_to_value is True
    assert dependency.map_from[0].model_extra["FutureTerm"] == 1
    assert result.model_extra["FutureMetadata"]["Revision"] == 7


@pytest.mark.parametrize("names", [["ExampleBios.1.2.0", "ExampleBios.1.2.2", "ExampleBios.2.0.0"],
                                  ["ExampleBios.2.0.0", "ExampleBios.1.2.2", "ExampleBios.1.2.0"]])
def test_compatible_version_selection_is_deterministic(client, names):
    client._get_registries_collection.return_value = [registry(name) for name in names]
    def get(path, model):
        payload = document()
        payload["RegistryVersion"] = path.rsplit("/", 1)[-1].removeprefix("ExampleBios.").removesuffix(".json")
        return model.model_validate(payload)
    client._http_client.get.side_effect = get
    assert client.get_attribute_registry("ExampleBios.1.2").registry_version == "1.2.2"
    assert client.get_attribute_registry("ExampleBios.1.2.0").registry_version == "1.2.0"
    with pytest.raises(RegistryResolutionError):
        client.get_attribute_registry("ExampleBios.1.3")


@pytest.mark.parametrize(("language", "expected"), [("fr-CA", "fr"), ("FR", "fr"), ("de", "en")])
def test_localized_selection(client, language, expected):
    locations = [{"Language": "fr", "Uri": "/fr.json"}, {"Language": "en", "Uri": "/en.json"}]
    client._get_registries_collection.return_value = [registry(locations=locations)]
    def get(path, model):
        payload = document()
        payload["Language"] = expected
        payload["RegistryEntries"]["Attributes"][0]["DisplayName"] = "Localized"
        return model.model_validate(payload)
    client._http_client.get.side_effect = get
    assert client.get_attribute_registry("ExampleBios.1.2.0", language=language).language == expected
    assert client._http_client.get.call_args.args[0] == f"/{expected}.json"


def test_document_family_is_not_inferred_from_registryfile(client):
    client._http_client.get.side_effect = lambda path, model: model.model_validate({"Messages": {}})
    with pytest.raises(RegistryResolutionError):
        client.get_attribute_registry("ExampleBios.1.2.0")
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MessageRegistry.model_validate(document())


def test_registry_version_mismatch_is_rejected(client):
    payload = document()
    payload["RegistryVersion"] = "2.0.0"
    client._http_client.get.side_effect = lambda path, model: model.model_validate(payload)
    with pytest.raises(RegistryResolutionError):
        client.get_attribute_registry("ExampleBios.1.2.0")


def test_cache_is_bounded_and_returns_independent_models(client):
    result = client.get_attribute_registry("ExampleBios.1.2.0")
    result.get_attribute("Mode").read_only = True
    assert client.get_attribute_registry("ExampleBios.1.2.0").get_attribute("Mode").read_only is False
    assert client._http_client.get.call_count == 1
    for index in range(33):
        client._get_registries_collection.return_value = [registry(f"Example{index}.1.2.0")]
        client.get_attribute_registry(f"Example{index}.1.2.0")
    assert len(client._attribute_registries._document_cache) == 32
    client.clear_registry_cache()
    assert not client._attribute_registries._document_cache


@pytest.mark.parametrize(("values", "valid"), [
    ({"Mode": "UEFI", "Enabled": False, "Count": 4, "Label": "Host"}, True),
    ({"Mode": "bad"}, False), ({"Count": True}, False), ({"Count": 3}, True),
    ({"Count": 10}, False), ({"Enabled": "false"}, False), ({"Label": "x"}, False),
    ({"Locked": "new"}, False), ({"Missing": 1}, False), ({"Password": "abc"}, False),
])
def test_static_attribute_validation(client, values, valid):
    result = client.get_attribute_registry("ExampleBios.1.2.0")
    if valid:
        result.validate_attribute_values(values)
    else:
        with pytest.raises(RedfishValidationError):
            result.validate_attribute_values(values)


def test_validation_does_not_expose_password_values(client):
    result = client.get_attribute_registry("ExampleBios.1.2.0")
    with pytest.raises(RedfishValidationError) as caught:
        result.validate_attribute_values({"Password": "x"})
    assert "'x'" not in str(caught.value)


def test_bios_registry_reference_is_discovered(client, monkeypatch):
    bios = Bios.model_validate({"AttributeRegistry": "ExampleBios.1.2.0"})
    monkeypatch.setattr(client._systems, "bios", lambda system_id=None: bios)
    result = client.get_bios_attribute_registry()
    assert result.get_attribute("Count").lower_bound == 2
    client.validate_bios_attributes({"Count": 4})


def test_missing_bios_reference_does_not_guess_registry(client, monkeypatch):
    monkeypatch.setattr(client._systems, "bios", lambda system_id=None: Bios.model_validate({}))
    with pytest.raises(RegistryResolutionError):
        client.get_bios_attribute_registry()
    client._http_client.get.assert_not_called()


def test_incomplete_and_future_registry_are_readable(client):
    payload = {"RegistryEntries": {"Attributes": [{"AttributeName": "Future", "Type": "FutureType"}]}}
    client._http_client.get.side_effect = lambda path, model: model.model_validate(payload)
    result = client.get_attribute_registry("ExampleBios.1.2.0")
    assert result.get_attribute("Future").type == "FutureType"
    assert result.registry_entries.menus == []
    with pytest.raises(RedfishValidationError):
        result.validate_attribute_values({"Future": "value"})


def test_opaque_vendor_ids_with_separate_localized_registryfiles(client):
    reference = "ExampleBios.v1_2_0"
    client._get_registries_collection.return_value = [
        Registry.model_validate({"Id": f"{reference}.{lang}", "Registry": reference,
            "Location": [{"Language": lang, "Uri": f"/{lang}.json"}]})
        for lang in ("en", "fr")
    ]
    def get(path, model):
        payload = document()
        payload["Language"] = path.strip("/").removesuffix(".json")
        return model.model_validate(payload)
    client._http_client.get.side_effect = get
    assert client.get_attribute_registry(reference, language="en").language == "en"
    assert client.get_attribute_registry(reference, language="fr").language == "fr"


def test_publication_document_uses_credential_free_transport(client, monkeypatch):
    client._get_registries_collection.return_value = [registry(locations=[
        {"Language": "en", "PublicationUri": "https://schemas.example/attributes.json"},
    ])]
    result = Mock()
    result.json.return_value = document()
    external = Mock()
    external.headers = {}
    external.get.return_value = result
    monkeypatch.setattr("redfish_sdk.managers.registries.requests.Session", Mock(return_value=external))
    assert client.get_attribute_registry("ExampleBios.1.2.0").registry_version == "1.2.0"
    assert external.trust_env is False
    assert external.get.call_args.kwargs["headers"] == {"Accept": "application/json"}
    external.cookies.clear.assert_called_once()
    external.close.assert_called_once()
    client._http_client.get.assert_not_called()


def test_no_registry_location_never_constructs_a_uri(client):
    client._get_registries_collection.return_value = [Registry.model_validate({"Id": "Opaque", "Registry": "Opaque"})]
    with pytest.raises(RegistryResolutionError):
        client.get_attribute_registry("Opaque")
    client._http_client.get.assert_not_called()


def test_nested_dependency_expressions_keep_their_types():
    from redfish_sdk import AttributeRegistry
    payload = document()
    payload["RegistryEntries"]["Dependencies"][0]["Dependency"]["MapFrom"] = [{
        "Subexpressions": [{"MapFromAttribute": "Count", "MapFromValue": 2, "MapFromCondition": "GTR"}],
        "MapTerms": "OR",
    }]
    result = AttributeRegistry.model_validate(payload)
    expression = result.registry_entries.dependencies[0].dependency.map_from[0]
    assert expression.subexpressions[0].map_from_value == 2
    assert type(expression.subexpressions[0].map_from_value) is int


def test_failed_resolution_does_not_poison_cache(client):
    client._http_client.get.side_effect = lambda path, model: model.model_validate({"Messages": {}})
    with pytest.raises(RegistryResolutionError):
        client.get_attribute_registry("ExampleBios.1.2.0")
    client._http_client.get.side_effect = lambda path, model: model.model_validate(document())
    assert client.get_attribute_registry("ExampleBios.1.2.0").get_attribute("Enabled").default_value is False


def test_bmc_failure_message_is_not_rewritten(client):
    from redfish_sdk import RedfishAuthError
    failure = RedfishAuthError(403, "Original downstream message")
    client._http_client.get.side_effect = failure
    with pytest.raises(RedfishAuthError) as caught:
        client.get_attribute_registry("ExampleBios.1.2.0")
    assert caught.value is failure


def test_scalar_increment_zero_means_free_form_numeric_input():
    from redfish_sdk import AttributeDefinition
    attribute = AttributeDefinition.model_validate({"AttributeName": "Count", "Type": "Integer",
        "ScalarIncrement": 0, "LowerBound": 0, "UpperBound": 10})
    attribute.validate_value(3)


def test_incomplete_identified_document_and_menu_remain_readable():
    from redfish_sdk import AttributeMenu, AttributeRegistry
    incomplete = AttributeRegistry.model_validate({"@odata.type": "#AttributeRegistry.v1_5_1.AttributeRegistry"})
    with pytest.raises(RegistryResolutionError):
        incomplete.get_attribute("Count")
    assert AttributeMenu.model_validate({"DisplayName": "Incomplete menu"}).menu_name is None


def test_unusable_localized_location_falls_back_to_usable_english(client):
    client._get_registries_collection.return_value = [registry(locations=[
        {"Language": "fr"}, {"Language": "en", "Uri": "/english.json"},
    ])]
    assert client.get_attribute_registry("ExampleBios.1.2.0", language="fr").language == "en"
    assert client._http_client.get.call_args.args[0] == "/english.json"
