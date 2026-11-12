"""Change-set planning is offline; execution uses mocked Requests adapters."""
import json
from dataclasses import FrozenInstanceError
from urllib.parse import urlsplit

import pytest
import requests

from redfish_sdk import ApplyTime, HttpMethod, RedfishClient, RedfishValidationError, SettingsApplyTime

ROOT = "/redfish/v1/"
ONE, TWO, THREE = (ROOT + "Systems/" + str(i) for i in (1, 2, 3))


class Adapter(requests.adapters.BaseAdapter):
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def send(self, request, **kwargs):
        self.calls.append(request)
        status, body, headers = self.handler(request)
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(body).encode()
        response.headers.update(headers)
        response.request, response.url = request, request.url
        return response

    def close(self):
        pass


@pytest.fixture
def client_factory():
    clients = []
    def make(handler=lambda request: (204, {}, {})):
        session = requests.Session()
        session.trust_env = False
        adapter = Adapter(handler)
        session.mount("https://", adapter)
        client = RedfishClient("bmc.example", "user", "password", session=session)
        clients.append((client, session))
        return client, adapter
    yield make
    for client, session in clients:
        client.close()
        session.close()


def test_staging_snapshots_payload_and_diff_without_network(client_factory):
    client, adapter = client_factory()
    changes = client.change_set()
    payload = {"Enabled": False, "Nested": {"Value": None}, "Password": "new-secret"}
    baseline = {"Enabled": True, "Nested": {"Value": "old"}, "Password": "old-secret"}
    changes.stage(HttpMethod.PATCH, ONE, body=payload, before=baseline)
    payload["Nested"]["Value"] = "mutated"
    baseline["Nested"]["Value"] = "mutated"
    assert changes.operations[0].body["Nested"]["Value"] is None
    detached = changes.operations[0].body
    detached["Enabled"] = True
    assert changes.operations[0].body["Enabled"] is False
    with pytest.raises(FrozenInstanceError):
        changes.operations[0].uri = TWO
    preview = changes.plan()
    assert preview[0]["body"]["Nested"]["Value"] is None
    diff = {item["path"]: item for item in preview[0]["diff"]}
    assert diff["/Enabled"]["before"] is True and diff["/Enabled"]["after"] is False
    assert diff["/Nested/Value"]["before"] == "old"
    assert diff["/Nested/Value"]["after"] is None
    assert "/Password" in diff  # Redaction must not erase a real secret change.
    rendered = changes.to_json()
    assert rendered == changes.to_json()
    assert "new-secret" not in rendered and "old-secret" not in rendered
    assert "new-secret" in changes.to_json(include_sensitive=True)
    assert "new-secret" not in repr(changes.operations[0])
    assert adapter.calls == []


def test_dry_run_validates_without_any_network_and_does_not_consume_plan(client_factory):
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={"Enabled": True}, expected_etag='"v1"')
    result = changes.commit(dry_run=True)
    assert result.dry_run and not result.is_partial
    assert result.results[0].status.value == "skipped"
    assert not result.results[0].attempted
    assert adapter.calls == []
    changes.stage(HttpMethod.POST, TWO, body={"Name": "second"})
    assert len(changes.operations) == 2


def test_validation_failure_prevents_first_write_and_reports_all_operations(client_factory):
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={"Enabled": True})
    changes.stage(HttpMethod.GET, TWO, body={})
    issues = changes.validate()
    assert [issue.operation_index for issue in issues] == [1]
    result = changes.commit()
    assert [item.status.value for item in result.results] == ["skipped", "failed"]
    assert not any(item.attempted for item in result.results)
    assert not result.is_partial
    assert adapter.calls == []


def test_custom_validator_fails_whole_plan_before_io(client_factory):
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={"Limit": -1})
    def validate(operation):
        if operation.body["Limit"] < 0:
            raise RedfishValidationError("Limit must be nonnegative")
    result = changes.commit(validator=validate)
    assert result.results[0].error.message == "Limit must be nonnegative"
    assert not result.results[0].attempted
    assert adapter.calls == []


def test_capture_etags_and_baseline_then_preflight_all_before_writes(client_factory):
    def handler(request):
        if request.method == "GET":
            return 200, {"Enabled": False}, {"ETag": 'W/"v1"'}
        assert request.headers["If-Match"] == 'W/"v1"'
        return 204, {}, {}
    client, adapter = client_factory(handler)
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={"Enabled": True})
    changes.stage(HttpMethod.PATCH, TWO, body={"Enabled": True})
    changes.capture_etags()
    assert [operation.expected_etag for operation in changes.operations] == ['W/"v1"'] * 2
    assert changes.plan()[0]["diff"][0]["before"] is False
    adapter.calls.clear()
    result = changes.commit()
    assert result.successful and not result.is_partial
    assert [request.method for request in adapter.calls] == ["GET", "GET", "PATCH", "PATCH"]
    assert [urlsplit(request.url).path for request in adapter.calls[-2:]] == [ONE, TWO]


def test_stale_etag_in_later_operation_prevents_every_write(client_factory):
    client, adapter = client_factory(lambda request: (200, {}, {"ETag": '"current"'}))
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={}, expected_etag='"current"')
    changes.stage(HttpMethod.PATCH, TWO, body={}, expected_etag='"stale"')
    result = changes.commit()
    assert [item.status.value for item in result.results] == ["skipped", "failed"]
    assert result.results[1].error.status_code == 412
    assert not result.is_partial
    assert all(request.method == "GET" for request in adapter.calls)


def test_mid_plan_failure_is_partial_fail_fast_with_downstream_message(client_factory):
    def handler(request):
        if urlsplit(request.url).path == TWO:
            return 400, {"error": {"code": "Base.1.0.GeneralError", "message": "Vendor rejected this value."}}, {}
        return 204, {}, {}
    client, adapter = client_factory(handler)
    changes = client.change_set()
    for uri in (ONE, TWO, THREE):
        changes.stage(HttpMethod.PATCH, uri, body={"Enabled": True})
    result = changes.commit()
    assert [item.status.value for item in result.results] == ["success", "failed", "skipped"]
    assert result.is_partial and not result.successful
    assert result.results[1].error.message == "Vendor rejected this value."
    assert len(adapter.calls) == 2
    with pytest.raises(RedfishValidationError):
        changes.commit()
    assert len(adapter.calls) == 2


def test_continue_on_error_is_explicit_and_keeps_staging_order(client_factory):
    client, adapter = client_factory(lambda request: (412, {}, {}) if urlsplit(request.url).path == TWO else (204, {}, {}))
    changes = client.change_set()
    for uri in (ONE, TWO, THREE):
        changes.stage(HttpMethod.DELETE, uri)
    result = changes.commit(continue_on_error=True)
    assert [item.status.value for item in result.results] == ["success", "failed", "success"]
    assert [urlsplit(request.url).path for request in adapter.calls] == [ONE, TWO, THREE]
    assert result.is_partial


def test_settings_apply_time_nested_model_is_preserved_in_wire_payload(client_factory):
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE + "/Bios/Settings", body={
        "Attributes": {"BootMode": "Uefi"},
        "@Redfish.SettingsApplyTime": SettingsApplyTime(apply_time=ApplyTime.ON_RESET),
    })
    assert changes.commit().successful
    assert json.loads(adapter.calls[0].body)["@Redfish.SettingsApplyTime"] == {"ApplyTime": "OnReset"}


def test_accepted_response_keeps_task_metadata_and_is_not_completed_success(client_factory):
    client, _ = client_factory(lambda request: (202, {}, {"Location": ROOT + "TaskService/Tasks/1", "Retry-After": "2"}))
    result = client.change_set().stage(HttpMethod.POST, ONE + "/Actions/ComputerSystem.Reset", body={}).commit()
    assert result.results[0].status.value == "accepted"
    assert result.pending and not result.successful
    assert result.results[0].response.location == ROOT + "TaskService/Tasks/1"


def test_transport_failure_is_uncertain_and_plan_is_not_replayed(client_factory):
    def handler(request):
        raise requests.ConnectionError("Connection lost after sending request")
    client, adapter = client_factory(handler)
    changes = client.change_set().stage(HttpMethod.POST, ONE, body={})
    result = changes.commit()
    assert result.results[0].status.value == "failed"
    assert result.results[0].outcome_unknown
    assert result.has_uncertain_outcomes and result.is_partial
    with pytest.raises(RedfishValidationError):
        changes.commit()
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("uri", ["https://other.example/resource", "//bmc.example/resource", "https://user:pass@bmc.example/resource"])
def test_untrusted_targets_rejected_before_network(client_factory, uri):
    client, adapter = client_factory()
    with pytest.raises(RedfishValidationError):
        client.change_set().stage(HttpMethod.PATCH, uri, body={})
    assert adapter.calls == []


def test_omitted_and_explicit_null_body_remain_distinct(client_factory):
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.POST, ONE)
    changes.stage(HttpMethod.POST, TWO, body=None)
    assert changes.operations[0].has_body is False
    assert changes.operations[1].has_body is True
    changes.commit()
    assert adapter.calls[0].body is None
    assert adapter.calls[1].body == "null"


def test_if_none_match_create_precondition_and_server_enforcement(client_factory):
    client, adapter = client_factory(lambda request: (404, {}, {}) if request.method == "GET" else (201, {}, {}))
    changes = client.change_set().stage(HttpMethod.PUT, ONE, body={"Name": "new"}, if_none_match="*")
    assert changes.commit().successful
    assert [request.method for request in adapter.calls] == ["GET", "PUT"]
    assert adapter.calls[-1].headers["If-None-Match"] == "*"


def test_if_none_match_specific_tag_allows_absent_resource(client_factory):
    client, _ = client_factory(lambda request: (404, {}, {}) if request.method == "GET" else (201, {}, {}))
    result = client.change_set().stage(HttpMethod.PUT, ONE, body={}, if_none_match='"previous"').commit()
    assert result.successful


def test_json_diff_distinguishes_booleans_inside_arrays_and_escapes_pointer_keys(client_factory):
    client, _ = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, before={"a/b~c": [False]}, body={"a/b~c": [0]})
    rows = changes.plan()[0]["diff"]
    assert len(rows) == 1
    assert rows[0]["path"] == "/a~1b~0c"
    assert rows[0]["before"] == [False] and rows[0]["after"] == [0]


def test_capture_failure_does_not_install_partial_etag_snapshots(client_factory):
    def handler(request):
        return (200, {"Enabled": False}, {"ETag": '"v1"'}) if urlsplit(request.url).path == ONE else (500, {}, {})
    client, adapter = client_factory(handler)
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={})
    changes.stage(HttpMethod.PATCH, TWO, body={})
    with pytest.raises(Exception) as error:
        changes.capture_etags()
    assert error.value.status_code == 500
    assert all(operation.expected_etag is None for operation in changes.operations)
    assert all(request.method == "GET" for request in adapter.calls)


def test_server_etag_race_is_reported_and_stops_later_writes(client_factory):
    client, adapter = client_factory(lambda request: (200, {}, {"ETag": '"v1"'}) if request.method == "GET" else (412, {}, {}))
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={}, expected_etag='"v1"')
    changes.stage(HttpMethod.PATCH, TWO, body={})
    result = changes.commit()
    assert result.results[0].attempted and result.results[0].error.status_code == 412
    assert result.results[1].status.value == "skipped"
    assert not result.has_uncertain_outcomes
    assert [request.method for request in adapter.calls] == ["GET", "PATCH"]


def test_disabling_read_preflight_keeps_conditional_wire_header(client_factory):
    client, adapter = client_factory()
    result = client.change_set().stage(HttpMethod.PATCH, ONE, body={}, expected_etag='"v1"').commit(check_etags=False)
    assert result.successful
    assert len(adapter.calls) == 1
    assert adapter.calls[0].headers["If-Match"] == '"v1"'


@pytest.mark.parametrize("options", [{"expected_etag": "unquoted"}, {"expected_etag": '"x"\r\nInjected: true'},
    {"expected_etag": '"x"', "if_none_match": "*"}])
def test_invalid_preconditions_block_all_network(client_factory, options):
    client, adapter = client_factory()
    result = client.change_set().stage(HttpMethod.PATCH, ONE, body={}, **options).commit()
    assert result.results[0].status.value == "failed"
    assert not result.results[0].attempted
    assert adapter.calls == []


def test_if_none_match_uses_weak_comparison(client_factory):
    client, adapter = client_factory(lambda request: (200, {}, {"ETag": 'W/"same"'}))
    result = client.change_set().stage(HttpMethod.PUT, ONE, body={}, if_none_match='"same"').commit()
    assert result.results[0].error.status_code == 412
    assert [request.method for request in adapter.calls] == ["GET"]


def test_put_diff_includes_removals_patch_diff_preserves_unspecified_fields(client_factory):
    client, _ = client_factory()
    changes = client.change_set().stage(HttpMethod.PUT, ONE, body={"Keep": 2}, before={"Keep": 1, "Remove": True})
    changes.stage(HttpMethod.PATCH, TWO, body={"Keep": 2}, before={"Keep": 1, "Remove": True})
    rows = changes.plan()
    deleted = next(row for row in rows[0]["diff"] if row["path"] == "/Remove")
    assert deleted["before_present"] and not deleted["after_present"]
    assert [row["path"] for row in rows[1]["diff"]] == ["/Keep"]


def test_missing_baseline_is_not_rendered_as_known_null(client_factory):
    client, _ = client_factory()
    row = client.change_set().stage(HttpMethod.PATCH, ONE, body={"Clear": None}).plan()[0]["diff"][0]
    assert not row["before_present"] and row["after_present"]
    assert "before" not in row and row["after"] is None


def test_empty_patch_body_has_no_claimed_property_replacements(client_factory):
    client, _ = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={}, before={"Enabled": True})
    assert changes.plan()[0]["diff"] == []


def test_redirect_and_server_errors_are_uncertain_without_following_or_retries(client_factory):
    client, adapter = client_factory(lambda request: (307, {}, {"Location": "https://other.example/"}))
    result = client.change_set().stage(HttpMethod.POST, ONE, body={}).commit()
    assert result.results[0].error.status_code == 307
    assert result.has_uncertain_outcomes
    assert len(adapter.calls) == 1


def test_invalid_json_payload_fails_staging_without_network(client_factory):
    client, adapter = client_factory()
    with pytest.raises(RedfishValidationError):
        client.change_set().stage(HttpMethod.PATCH, ONE, body={"Number": float("nan")})
    assert adapter.calls == []


def test_typed_model_explicit_null_and_unset_fields_preserve_presence(client_factory):
    from pydantic import BaseModel
    from typing import Optional
    class Payload(BaseModel):
        clear: Optional[str] = None
        omit: Optional[str] = None
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body=Payload(clear=None))
    assert changes.commit().successful
    assert json.loads(adapter.calls[0].body) == {"clear": None}


def test_validator_cannot_append_unvalidated_operations(client_factory):
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={})
    def validator(operation):
        changes.stage(HttpMethod.DELETE, TWO)
    result = changes.commit(validator=validator)
    assert result.results[0].status.value == "failed"
    assert len(changes.operations) == 1
    assert adapter.calls == []


def test_capture_uses_http_etag_from_target_not_settings_metadata(client_factory):
    client, adapter = client_factory(lambda request: (200, {"@Redfish.Settings": {"ETag": '"historical"'}}, {}))
    changes = client.change_set().stage(HttpMethod.PATCH, ONE + "/Bios/Settings", body={})
    with pytest.raises(RedfishValidationError, match="HTTP ETag"):
        changes.capture_etags()
    assert changes.operations[0].expected_etag is None
    assert all(request.method == "GET" for request in adapter.calls)


def test_capture_tag_only_does_not_require_json_baseline(client_factory):
    client, _ = client_factory(lambda request: (200, None, {"ETag": '"v1"'}))
    changes = client.change_set().stage(HttpMethod.DELETE, ONE)
    changes.capture_etags(include_before=False)
    assert changes.operations[0].expected_etag == '"v1"'
    assert changes.operations[0].before_json is None


def test_two_writes_to_same_resource_do_not_refresh_approved_etag(client_factory):
    state = {"tag": '"v1"'}
    def handler(request):
        if request.method == "GET":
            return 200, {}, {"ETag": state["tag"]}
        if request.headers["If-Match"] != state["tag"]:
            return 412, {}, {}
        state["tag"] = '"v2"'
        return 204, {}, {}
    client, adapter = client_factory(handler)
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={"First": True}, expected_etag='"v1"')
    changes.stage(HttpMethod.PATCH, ONE, body={"Second": True}, expected_etag='"v1"')
    result = changes.commit()
    assert [item.status.value for item in result.results] == ["success", "failed"]
    assert result.is_partial
    assert [request.method for request in adapter.calls] == ["GET", "PATCH", "PATCH"]


def test_server_failure_is_uncertain_and_writes_are_single_shot(client_factory):
    client, adapter = client_factory(lambda request: (500, {}, {}))
    result = client.change_set().stage(HttpMethod.POST, ONE, body={}).commit()
    assert result.has_uncertain_outcomes and result.is_partial
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("method", [HttpMethod.PATCH, HttpMethod.PUT])
def test_missing_required_body_fails_validation_before_network(client_factory, method):
    client, adapter = client_factory()
    result = client.change_set().stage(method, ONE).commit()
    assert result.results[0].status.value == "failed"
    assert adapter.calls == []


def test_existing_resource_blocks_if_none_match_wildcard(client_factory):
    client, adapter = client_factory(lambda request: (200, {}, {}))
    result = client.change_set().stage(HttpMethod.PUT, ONE, body={}, if_none_match="*").commit()
    assert result.results[0].error.status_code == 412
    assert all(request.method == "GET" for request in adapter.calls)


def test_plan_display_mutation_cannot_change_wire_intent(client_factory):
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={"Enabled": False})
    view = changes.plan()
    view[0]["body"]["Enabled"] = True
    changes.commit()
    assert json.loads(adapter.calls[0].body) == {"Enabled": False}
    with pytest.raises(RedfishValidationError):
        changes.stage(HttpMethod.DELETE, TWO)


def test_custom_root_bare_targets_are_bound_when_staged(client_factory):
    client, adapter = client_factory()
    client._http_client.service_root = "/gateway/redfish/v1/"
    changes = client.change_set().stage(HttpMethod.PATCH, "Systems/1", body={})
    client._http_client.service_root = "/different/"
    assert changes.commit().successful
    assert urlsplit(adapter.calls[0].url).path == "/gateway/redfish/v1/Systems/1"


def test_empty_put_diff_lists_removed_properties_and_omitted_post_has_no_diff(client_factory):
    client, _ = client_factory()
    changes = client.change_set().stage(HttpMethod.PUT, ONE, body={}, before={"Removed": True})
    changes.stage(HttpMethod.POST, TWO)
    preview = changes.plan()
    assert preview[0]["diff"][0]["path"] == "/Removed"
    assert not preview[0]["diff"][0]["after_present"]
    assert preview[1]["diff"] == []


def test_sensitive_export_requires_boolean_opt_in(client_factory):
    client, adapter = client_factory()
    changes = client.change_set().stage(HttpMethod.PATCH, ONE, body={"Password": "private-value"})
    with pytest.raises(RedfishValidationError):
        changes.to_json(include_sensitive="false")
    assert adapter.calls == []


@pytest.mark.parametrize("status", [302, 307])
def test_redirect_failure_preserves_downstream_message_and_context(client_factory, status):
    message = "Use the vendor-specific configuration endpoint."
    client, adapter = client_factory(lambda request: (status, {"error": {"message": message}}, {"Location": TWO}))
    result = client.change_set().stage(HttpMethod.POST, ONE, body={}).commit()
    error = result.results[0].error
    assert error.status_code == status and error.message == message
    assert error.method == "POST" and error.path.endswith(ONE)
    assert len(adapter.calls) == 1


def test_preflight_redirect_preserves_downstream_message_without_writes(client_factory):
    message = "The settings resource moved."
    client, adapter = client_factory(lambda request: (302, {"error": {"message": message}}, {"Location": TWO}))
    result = client.change_set().stage(HttpMethod.PATCH, ONE, body={}, expected_etag='"v1"').commit()
    assert result.results[0].error.message == message
    assert all(request.method == "GET" for request in adapter.calls)
