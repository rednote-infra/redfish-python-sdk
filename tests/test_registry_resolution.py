"""Message-registry resolution and 2026.2 message metadata tests."""
from __future__ import annotations

from typing import Optional
from unittest.mock import Mock

import pytest

from redfish_sdk import RedfishClient, RegistryResolutionError
from redfish_sdk.models.common import Condition, ExtendedInfo
from redfish_sdk.models.event import EventRecord, Subscription
from redfish_sdk.models.logs import LogEntry
from redfish_sdk.models.registry import MessageRegistry, Registry
from redfish_sdk.models.task import Message


def _registry(
    name: str,
    *locations: tuple[str, str],
) -> Registry:
    return Registry.model_validate(
        {
            "Id": name,
            "Registry": name.rsplit(".", 1)[0],
            "Languages": [language for language, _ in locations],
            "Location": [
                {"Language": language, "Uri": uri}
                for language, uri in locations
            ],
        }
    )


def _client(registries: list[Registry], documents: dict[str, dict]) -> RedfishClient:
    client = RedfishClient("bmc.example", "admin", "secret")
    client._get_registries_collection = Mock(return_value=registries)

    def get(path: str, model_class):
        if path not in documents:
            raise AssertionError(f"Unexpected registry document request: {path}")
        return model_class.model_validate(documents[path])

    client._http_client.get = Mock(side_effect=get)
    return client


def _message_registry(
    prefix: str,
    version: str,
    messages: dict,
    *,
    language: str = "en",
    referenced_registry: Optional[str] = None,
) -> dict:
    payload = {
        "RegistryPrefix": prefix,
        "RegistryVersion": version,
        "OwningEntity": "DMTF",
        "Language": language,
        "Messages": messages,
    }
    if referenced_registry:
        payload["ReferencedRegistry"] = referenced_registry
    return payload


def _message(text: str, *, args: int = 0) -> dict:
    return {
        "Description": "Test message",
        "Message": text,
        "MessageSeverity": "Warning",
        "NumberOfArgs": args,
        "ParamTypes": ["string"] * args,
        "Resolution": "Follow the recommended action.",
    }


def test_resolves_and_formats_direct_message() -> None:
    client = _client(
        [_registry("Base.1.18.0", ("en", "/registries/en/Base.json"))],
        {
            "/registries/en/Base.json": _message_registry(
                "Base",
                "1.18.0",
                {"PropertyValueError": _message("Value %1 is invalid for %2.", args=2)},
            )
        },
    )

    resolved = client.resolve_message(
        "Base.1.18.PropertyValueError", ["bad", "Mode"]
    )

    assert resolved.requested_message_id == "Base.1.18.PropertyValueError"
    assert resolved.message_id == "Base.1.18.PropertyValueError"
    assert resolved.message == "Value bad is invalid for Mode."
    assert resolved.message_severity == "Warning"
    assert resolved.resolution == "Follow the recommended action."


def test_selects_language_then_falls_back_to_english() -> None:
    registry = _registry(
        "Base.1.18.0",
        ("en", "/registries/en/Base.json"),
        ("fr", "/registries/fr/Base.json"),
    )
    client = _client(
        [registry],
        {
            "/registries/en/Base.json": _message_registry(
                "Base", "1.18.0", {"Done": _message("Done")}
            ),
            "/registries/fr/Base.json": _message_registry(
                "Base", "1.18.0", {"Done": _message("Termine")}, language="fr"
            ),
        },
    )

    assert client.resolve_message("Base.1.18.Done", language="fr-CA").message == "Termine"
    assert client.resolve_message("Base.1.18.Done", language="de").message == "Done"


def test_matches_major_minor_and_uses_highest_errata() -> None:
    client = _client(
        [
            _registry("Base.1.17.9", ("en", "/Base-1.17.json")),
            _registry("Base.1.18.0", ("en", "/Base-1.18.0.json")),
            _registry("Base.1.18.2", ("en", "/Base-1.18.2.json")),
        ],
        {
            "/Base-1.18.2.json": _message_registry(
                "Base", "1.18.2", {"Done": _message("Newest errata")}
            )
        },
    )

    resolved = client.resolve_message("Base.1.18.Done")

    assert resolved.registry_version == "1.18.2"
    assert resolved.message == "Newest errata"


def test_resolves_per_message_reference_and_returns_source_message_id() -> None:
    client = _client(
        [
            _registry("Platform.1.5.0", ("en", "/Platform.json")),
            _registry("Device.1.0.0", ("en", "/Device.json")),
        ],
        {
            "/Platform.json": _message_registry(
                "Platform",
                "1.5.0",
                {"SharedMessage": {"ReferencedRegistry": "Device.1.0.0"}},
            ),
            "/Device.json": _message_registry(
                "Device", "1.0.0", {"SharedMessage": _message("From Device")}
            ),
        },
    )

    resolved = client.resolve_message("Platform.1.5.SharedMessage")

    assert resolved.requested_message_id == "Platform.1.5.SharedMessage"
    assert resolved.message_id == "Device.1.0.SharedMessage"
    assert resolved.message == "From Device"


def test_resolves_normative_document_level_reference() -> None:
    client = _client(
        [
            _registry("Alias.1.0.0", ("en", "/Alias.json")),
            _registry("Source.2.3.1", ("en", "/Source.json")),
        ],
        {
            "/Alias.json": {
                "ReferencedRegistry": "Source.2.3.1",
                "VersionAdded": "v1_9_0",
            },
            "/Source.json": _message_registry(
                "Source", "2.3.1", {"Shared": _message("From source")}
            ),
        },
    )

    resolved = client.resolve_message("Alias.1.0.Shared")

    assert resolved.message_id == "Source.2.3.Shared"
    assert resolved.message == "From source"


@pytest.mark.parametrize(
    ("message_id", "error_match"),
    [
        ("Unknown.1.0.Message", "Unknown registry prefix"),
        ("Base.invalid.Message", "Invalid MessageId"),
    ],
)
def test_reports_unresolvable_message_ids(message_id: str, error_match: str) -> None:
    client = _client([], {})

    with pytest.raises(RegistryResolutionError, match=error_match):
        client.resolve_message(message_id)


def test_reports_missing_registry_file() -> None:
    client = _client(
        [_registry("Base.1.18.0", ("en", "/missing.json"))],
        {},
    )
    client._http_client.get.side_effect = RuntimeError("file is missing")

    with pytest.raises(RegistryResolutionError, match="Unable to load registry document"):
        client.resolve_message("Base.1.18.Done")


def test_detects_reference_cycles() -> None:
    client = _client(
        [
            _registry("First.1.0.0", ("en", "/First.json")),
            _registry("Second.1.0.0", ("en", "/Second.json")),
        ],
        {
            "/First.json": _message_registry(
                "First", "1.0.0", {"Loop": {"ReferencedRegistry": "Second.1.0.0"}}
            ),
            "/Second.json": _message_registry(
                "Second", "1.0.0", {"Loop": {"ReferencedRegistry": "First.1.0.0"}}
            ),
        },
    )

    with pytest.raises(RegistryResolutionError, match="reference cycle"):
        client.resolve_message("First.1.0.Loop")


def test_external_publication_does_not_receive_bmc_credentials(monkeypatch) -> None:
    registry = Registry.model_validate(
        {
            "Id": "Base.1.18.0",
            "Registry": "Base.1.18",
            "RegistryVersion": "1.18.0",
            "Languages": ["en"],
            "Location": [
                {
                    "Language": "en",
                    "PublicationUri": "https://schemas.example/Base.json",
                }
            ],
        }
    )
    client = _client([registry], {})
    response = Mock()
    response.json.return_value = _message_registry(
        "Base", "1.18.0", {"Done": _message("Done")}
    )
    response.raise_for_status.return_value = None
    external_session = Mock()
    external_session.headers = {}
    external_session.cookies = Mock()
    external_session.get.return_value = response
    monkeypatch.setattr(
        "redfish_sdk.managers.registries.requests.Session",
        Mock(return_value=external_session),
    )

    client.resolve_message("Base.1.18.Done")

    _, kwargs = external_session.get.call_args
    assert kwargs["headers"] == {"Accept": "application/json"}
    assert "Authorization" not in external_session.headers
    assert "X-Auth-Token" not in external_session.headers
    external_session.cookies.clear.assert_called_once_with()
    external_session.close.assert_called_once_with()


def test_registry_document_cache_is_bounded() -> None:
    registries = [
        _registry(f"Registry{index}.1.0.0", ("en", f"/Registry{index}.json"))
        for index in range(33)
    ]
    documents = {
        f"/Registry{index}.json": _message_registry(
            f"Registry{index}", "1.0.0", {"Done": _message("Done")}
        )
        for index in range(33)
    }
    client = _client(registries, documents)

    for index in range(33):
        client.resolve_message(f"Registry{index}.1.0.Done")

    assert len(client._registries._document_cache) == 32
    assert "/Registry0.json" not in client._registries._document_cache


def test_registry_document_model_preserves_oem_data() -> None:
    registry = MessageRegistry.model_validate(
        {
            **_message_registry("OEM", "1.0.0", {"Notice": _message("Notice")}),
            "Oem": {"Contoso": {"Code": 7}},
        }
    )

    assert registry.model_dump(by_alias=True)["Oem"]["Contoso"]["Code"] == 7


def test_vendor_code_is_typed_on_2026_2_message_surfaces() -> None:
    payload = {"MessageId": "OEM.1.0.Code", "VendorCode": "legacy-42"}

    assert ExtendedInfo.model_validate(payload).vendor_code == "legacy-42"
    assert Message.model_validate(payload).vendor_code == "legacy-42"
    assert LogEntry.model_validate(payload).vendor_code == "legacy-42"
    assert EventRecord.model_validate(payload).vendor_code == "legacy-42"
    assert Condition.model_validate(payload).vendor_code == "legacy-42"


def test_subscription_models_accept_source_and_legacy_registry_filters() -> None:
    subscription = Subscription.model_validate(
        {
            "RegistryPrefixes": ["Device", "Platform"],
            "MessageIds": ["Device.1.0.Shared", "Platform.1.4.LegacyDeviceMessage"],
        }
    )

    assert subscription.registry_prefixes == ["Device", "Platform"]
    assert subscription.message_ids == [
        "Device.1.0.Shared",
        "Platform.1.4.LegacyDeviceMessage",
    ]
