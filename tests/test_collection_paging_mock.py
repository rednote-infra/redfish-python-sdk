"""Offline coverage for Redfish collection paging and partial failures."""

from unittest.mock import Mock

import pytest

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishException, RedfishValidationError
from redfish_sdk.models.systems import System


@pytest.fixture
def client():
    result = RedfishClient(host="mock-bmc", username="user", password="password")
    yield result
    result.close()


def _system(identifier):
    return System.model_validate(
        {"@odata.id": f"/redfish/v1/Systems/{identifier}", "Id": identifier}
    )


def test_collection_follows_opaque_pages_and_deduplicates_members(client, monkeypatch):
    pages = {
        "/redfish/v1/Systems": {
            "Members": [{"@odata.id": "/redfish/v1/Systems/1"}],
            "Members@odata.nextLink": "?page=2&token=opaque%2Bvalue",
        },
        "/redfish/v1/Systems?page=2&token=opaque%2Bvalue": {
            "Members": [],
            "Members@odata.nextLink": "https://mock-bmc/redfish/v1/Systems?page=3",
        },
        "/redfish/v1/Systems?page=3": {
            "Members": [
                {"@odata.id": "/redfish/v1/Systems/1"},
                {"@odata.id": "/redfish/v1/Systems/2"},
            ]
        },
    }
    get_raw = Mock(side_effect=lambda path: pages[path])
    get = Mock(side_effect=lambda path, model: _system(path.rsplit("/", 1)[-1]))
    monkeypatch.setattr(client._http_client, "get_raw", get_raw)
    monkeypatch.setattr(client._http_client, "get", get)

    result = client._get_collection("/redfish/v1/Systems", System)

    assert [system.id for system in result] == ["1", "2"]
    assert result.is_partial is False
    assert result.failures == []
    assert [call.args[0] for call in get_raw.call_args_list] == list(pages)
    assert [call.args[0] for call in get.call_args_list] == [
        "/redfish/v1/Systems/1",
        "/redfish/v1/Systems/2",
    ]


def test_collection_cycle_returns_structured_partial_diagnostic(client, monkeypatch):
    pages = {
        "/redfish/v1/Systems": {
            "Members": [{"@odata.id": "/redfish/v1/Systems/1"}],
            "Members@odata.nextLink": "/redfish/v1/Systems?page=2",
        },
        "/redfish/v1/Systems?page=2": {
            "Members": [],
            "Members@odata.nextLink": "/redfish/v1/Systems",
        },
    }
    get_raw = Mock(side_effect=lambda path: pages[path])
    monkeypatch.setattr(client._http_client, "get_raw", get_raw)
    monkeypatch.setattr(client._http_client, "get", lambda path, model: _system("1"))

    result = client._get_collection("/redfish/v1/Systems", System)

    assert [system.id for system in result] == ["1"]
    assert result.is_partial is True
    assert len(result.failures) == 1
    assert result.failures[0].stage == "page"
    assert result.failures[0].resource == "/redfish/v1/Systems"
    assert isinstance(result.failures[0].error, RedfishValidationError)
    assert get_raw.call_count == 2


def test_collection_member_failure_is_distinct_from_empty_collection(client, monkeypatch):
    failure = RedfishException(500, "member failed", "original response")
    monkeypatch.setattr(
        client._http_client,
        "get_raw",
        lambda path: {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]},
    )
    monkeypatch.setattr(client._http_client, "get", Mock(side_effect=failure))

    result = client._get_collection("/redfish/v1/Systems", System)

    assert result == []
    assert result.is_partial is True
    assert len(result.failures) == 1
    assert result.failures[0].stage == "member"
    assert result.failures[0].error is failure


def test_strict_collection_mode_preserves_member_exception(monkeypatch):
    client = RedfishClient(
        host="mock-bmc",
        username="user",
        password="password",
        strict_collection_errors=True,
    )
    failure = RedfishException(500, "member failed", "original response")
    monkeypatch.setattr(
        client._http_client,
        "get_raw",
        lambda path: {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]},
    )
    monkeypatch.setattr(client._http_client, "get", Mock(side_effect=failure))

    with pytest.raises(RedfishException) as raised:
        client._get_collection("/redfish/v1/Systems", System)

    assert raised.value is failure
    client.close()


def test_continuation_failure_returns_partial_result(client, monkeypatch):
    failure = RedfishException(503, "page unavailable", "original response")

    def get_raw(path):
        if path == "/redfish/v1/Systems":
            return {
                "Members": [{"@odata.id": "/redfish/v1/Systems/1"}],
                "Members@odata.nextLink": "/redfish/v1/Systems?page=2",
            }
        raise failure

    monkeypatch.setattr(client._http_client, "get_raw", get_raw)
    monkeypatch.setattr(client._http_client, "get", lambda path, model: _system("1"))

    result = client._get_collection("/redfish/v1/Systems", System)

    assert [system.id for system in result] == ["1"]
    assert result.is_partial is True
    assert result.failures[0].resource == "/redfish/v1/Systems?page=2"
    assert result.failures[0].error is failure


def test_strict_collection_mode_preserves_continuation_exception(monkeypatch):
    client = RedfishClient(
        host="mock-bmc",
        username="user",
        password="password",
        strict_collection_errors=True,
    )
    failure = RedfishException(503, "page unavailable", "original response")

    def get_raw(path):
        if path == "/redfish/v1/Systems":
            return {
                "Members": [],
                "Members@odata.nextLink": "/redfish/v1/Systems?page=2",
            }
        raise failure

    monkeypatch.setattr(client._http_client, "get_raw", get_raw)

    with pytest.raises(RedfishException) as raised:
        client._get_collection("/redfish/v1/Systems", System)

    assert raised.value is failure
    client.close()


def test_initial_page_failure_keeps_existing_exception_behavior(client, monkeypatch):
    failure = RedfishException(503, "page unavailable", "original response")
    monkeypatch.setattr(client._http_client, "get_raw", Mock(side_effect=failure))

    with pytest.raises(RedfishException) as raised:
        client._get_collection("/redfish/v1/Systems", System)

    assert raised.value is failure


def test_cross_origin_next_link_is_blocked_without_forwarding_credentials(
    client, monkeypatch
):
    get_raw = Mock(
        return_value={
            "Members": [],
            "Members@odata.nextLink": "https://attacker.invalid/redfish/v1/Systems",
        }
    )
    monkeypatch.setattr(client._http_client, "get_raw", get_raw)

    result = client._get_collection("/redfish/v1/Systems", System)

    assert result == []
    assert result.is_partial is True
    assert isinstance(result.failures[0].error, RedfishValidationError)
    assert get_raw.call_count == 1


def test_non_paged_collection_does_not_construct_continuation_url(client, monkeypatch):
    get_raw = Mock(return_value={"Members": []})
    monkeypatch.setattr(client._http_client, "get_raw", get_raw)

    result = client._get_collection("/custom/collection?view=current", System)

    assert result == []
    assert result.is_partial is False
    get_raw.assert_called_once_with("/custom/collection?view=current")
