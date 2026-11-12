"""Offline graph traversal, selection, bounds and untrusted-link coverage."""
import json
from urllib.parse import urlsplit

import pytest
import requests

from redfish_sdk import RedfishClient, RedfishValidationError

ROOT = "/gateway/redfish/v1/"
SYSTEM = "#ComputerSystem.v1_23_0.ComputerSystem"


def document(uri, kind="ComputerSystem", **properties):
    return {"@odata.id": uri, "@odata.type": f"#{kind}.v1_0_0.{kind}", **properties}


class GraphAdapter(requests.adapters.BaseAdapter):
    def __init__(self, graph):
        self.graph, self.calls = graph, []

    def send(self, request, **kwargs):
        target = urlsplit(request.url)
        uri = target.path + ("?" + target.query if target.query else "")
        self.calls.append(uri)
        value = self.graph.get(uri, 404)
        response = requests.Response()
        status, payload = value if isinstance(value, tuple) else (value, {}) if isinstance(value, int) else (200, value)
        response.status_code = status
        response._content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        response.request, response.url = request, request.url
        return response

    def close(self):
        pass


@pytest.fixture
def client_factory():
    clients = []
    def make(graph, root=ROOT, host="bmc.example"):
        session = requests.Session()
        session.trust_env = False
        adapter = GraphAdapter(graph)
        session.mount("https://", adapter)
        client = RedfishClient(host, "user", "password", session=session, service_root=root)
        clients.append((client, session))
        return client, adapter
    yield make
    for client, session in clients:
        client.close()
        session.close()


def test_index_types_oem_nested_links_cycles_and_pagination(client_factory):
    systems = ROOT + "Systems"
    one, two = systems + "/1", systems + "/2"
    graph = {
        ROOT: document(ROOT, "ServiceRoot", Systems={"@odata.id": "Systems"}, Again={"@odata.id": "Systems"}),
        systems: document(systems, "ComputerSystemCollection", Members=[{"@odata.id": "Systems/1"}],
                          **{"Members@odata.nextLink": "?page=2&token=opaque%2Bvalue"}),
        systems + "?page=2&token=opaque%2Bvalue": document(systems, "ComputerSystemCollection",
            Members=[{"@odata.id": two}], **{"Members@odata.nextLink": systems}),
        one: {"@odata.id": one, "@odata.type": SYSTEM, "Manufacturer": "Example", "Enabled": False,
              "Links": {"Back": {"@odata.id": ROOT}}, "Oem": {"Vendor": {"@odata.id": ROOT + "OEM/1"}}},
        two: document(two, Manufacturer="Other", Enabled=True),
        ROOT + "OEM/1": {"@odata.id": ROOT + "OEM/1", "@odata.type": "#AcmeWidget.v2_1_0.AcmeWidget", "Value": 0},
    }
    client, adapter = client_factory(graph)
    index = client.discover_resources()
    assert not index.is_partial
    assert SYSTEM in index.types
    assert "#AcmeWidget.v2_1_0.AcmeWidget" in index.types
    assert len(index) == 5  # Paging does not duplicate the collection descriptor.
    assert len(adapter.calls) == len(set(adapter.calls)) == 6
    selected = index.find(odata_type="ComputerSystem", where={"Manufacturer": "Example", "Enabled": False})
    assert [item.uri for item in selected] == [one]
    assert selected[0].properties["Enabled"] is False
    assert len(index.find(odata_type=SYSTEM)) == 1
    assert len(index.find(odata_type="AcmeWidget", where={"Value": 0})) == 1
    assert not index.find(where={"Absent": None})
    assert not index.find(where={"Enabled": 0})  # JSON bool is not a numeric zero.


def test_find_resources_keeps_diagnostics_when_filter_has_no_matches(client_factory):
    client, _ = client_factory({ROOT: document(ROOT, "ServiceRoot", Broken={"@odata.id": "Missing"})})
    result = client.find_resources(odata_type="ComputerSystem")
    assert not result
    assert result.is_partial
    assert len(result.failures) == 1
    assert result.failures[0].uri == ROOT + "Missing"
    assert result.failures[0].error.status_code == 404


@pytest.mark.parametrize("link", ["https://other.example/root", "https://user:password@bmc.example/root",
    "//bmc.example/root", "http://bmc.example/root", "https://[invalid]/root", "javascript:alert(1)",
    "https://bmc.example\\@other.example/root", 123])
def test_untrusted_links_are_reported_without_requests(client_factory, link):
    client, adapter = client_factory({ROOT: document(ROOT, "ServiceRoot", Bad={"@odata.id": link})})
    result = client.discover_resources()
    assert result.is_partial
    assert len(result.failures) == 1
    assert adapter.calls == [ROOT]


def test_subtree_scope_and_depth_limit(client_factory):
    start = ROOT + "Systems/1"
    child = start + "/Processors"
    client, adapter = client_factory({start: document(start, Child={"@odata.id": child},
        Parent={"@odata.id": ROOT}), child: document(child, "ProcessorCollection")})
    index = client.discover_resources(start=start, max_depth=0)
    assert [item.uri for item in index] == [start]
    assert index.is_partial
    assert index.limits_reached == ("max_depth",)
    assert adapter.calls == [start]
    full = client.discover_resources(start=start, max_depth=1)
    assert len(full) == 2
    assert not full.is_partial
    assert ROOT in full.excluded


def test_request_budget_includes_failed_requests_and_bounds_queue(client_factory):
    graph = {ROOT: document(ROOT, "ServiceRoot", Children=[{"@odata.id": f"Items/{i}"} for i in range(20)])}
    client, adapter = client_factory(graph)
    index = client.discover_resources(max_resources=3)
    assert len(adapter.calls) == 3
    assert len(index.failures) == 2
    assert index.limits_reached == ("max_resources",)
    assert index.is_partial


def test_expensive_collections_require_opt_in_even_with_encoded_paths(client_factory):
    logs, telemetry = ROOT + "LogServices", ROOT + "TelemetryService"
    graph = {ROOT: document(ROOT, "ServiceRoot", LogServices={"@odata.id": logs},
             TelemetryService={"@odata.id": telemetry}, Hidden={"@odata.id": ROOT + "%4CogServices"}),
             logs: document(logs, "LogServiceCollection"), telemetry: document(telemetry, "TelemetryService")}
    client, adapter = client_factory(graph)
    index = client.discover_resources()
    assert len(index) == 1 and not index.is_partial
    assert adapter.calls == [ROOT]
    assert logs in index.excluded and telemetry in index.excluded
    client.discover_resources(include_expensive=True)
    assert logs in adapter.calls and telemetry in adapter.calls


@pytest.mark.parametrize("bad", [[], {}, {"@odata.id": "bad", "@odata.type": 1},
                                  {"@odata.id": "bad", "@odata.type": "not-a-type"}])
def test_malformed_resources_report_partial_failure(client_factory, bad):
    client, _ = client_factory({ROOT: bad})
    index = client.discover_resources()
    assert not index
    assert index.is_partial
    assert len(index.failures) == 1


@pytest.mark.parametrize("options", [{"max_depth": -1}, {"max_depth": True}, {"max_resources": 0},
    {"max_resources": True}, {"include_expensive": "yes"}, {"start": "https://other.example/root"}])
def test_invalid_options_fail_before_io(client_factory, options):
    client, adapter = client_factory({})
    with pytest.raises(RedfishValidationError):
        client.discover_resources(**options)
    assert adapter.calls == []


def test_standard_root_remains_default(client_factory):
    client, adapter = client_factory({"/redfish/v1/": document("/redfish/v1/", "ServiceRoot")}, root="/redfish/v1/")
    assert client.discover_resources().types == ("#ServiceRoot.v1_0_0.ServiceRoot",)
    assert adapter.calls == ["/redfish/v1/"]


def test_paging_at_depth_zero_deduplicates_resource_identity(client_factory):
    graph = {ROOT: document(ROOT, "ComputerSystemCollection", **{"Members@odata.nextLink": "?page=2"}),
             ROOT + "?page=2": document(ROOT, "ComputerSystemCollection", **{"Members@odata.nextLink": ROOT})}
    client, adapter = client_factory(graph)
    index = client.discover_resources(max_depth=0)
    assert not index.is_partial
    assert len(index) == 1
    assert adapter.calls == [ROOT, ROOT + "?page=2"]


def test_exact_json_filters_distinguish_null_missing_boolean_and_nested_values(client_factory):
    payload = document(ROOT, "ServiceRoot", Null=None, Flag=True, Nested={"Values": [False, 0, ""]})
    client, _ = client_factory({ROOT: payload})
    index = client.discover_resources()
    assert len(index.find(where={"Null": None, "Flag": True, "Nested": {"Values": [False, 0, ""]}})) == 1
    assert not index.find(where={"Missing": None})
    assert not index.find(where={"Flag": 1})
    assert not index.find(where={"Nested": {"Values": [0, 0, ""]}})
    assert index[0].properties == payload
    assert "Nested" not in repr(index[0])


@pytest.mark.parametrize("selector", [{"odata_type": ""}, {"odata_type": "Computer*"}, {"where": []}, {"where": {1: 2}}])
def test_invalid_selection_fails_before_traversal(client_factory, selector):
    client, adapter = client_factory({})
    with pytest.raises(RedfishValidationError):
        client.find_resources(**selector)
    assert adapter.calls == []


def test_redirects_are_reported_as_failures(client_factory):
    client, adapter = client_factory({ROOT: 302})
    index = client.discover_resources()
    assert index.is_partial and len(index.failures) == 1
    assert index.failures[0].error.status_code == 302
    assert adapter.calls == [ROOT]


def test_expensive_type_on_opaque_uri_stops_descendant_traversal(client_factory):
    opaque = ROOT + "Opaque"
    graph = {ROOT: document(ROOT, "ServiceRoot", Hidden={"@odata.id": opaque}),
             opaque: document(opaque, "LogService", Entries={"@odata.id": opaque + "/Items"})}
    client, adapter = client_factory(graph)
    result = client.discover_resources()
    assert len(result) == 1 and not result.is_partial
    assert opaque in result.excluded
    assert adapter.calls == [ROOT, opaque]


def test_index_repr_hides_sensitive_resource_and_rejected_link_data(client_factory):
    client, _ = client_factory({ROOT: document(ROOT, "ServiceRoot", Password="private-value",
        Bad={"@odata.id": "https://user:rejected-secret@bmc.example/private"})})
    index = client.discover_resources()
    assert "private-value" not in repr(index)
    assert "rejected-secret" not in repr(index)
    assert "rejected-secret" in index.failures[0].uri  # Raw attributes remain available.


def test_invalid_resource_type_does_not_enter_index(client_factory):
    client, _ = client_factory({ROOT: {"@odata.id": ROOT, "@odata.type": SYSTEM + "\n"}})
    index = client.discover_resources()
    assert not index and index.is_partial


def test_foreign_declared_identity_is_rejected_and_not_expanded(client_factory):
    client, adapter = client_factory({ROOT: {"@odata.id": "https://other.example/resource", "@odata.type": SYSTEM,
        "Child": {"@odata.id": ROOT + "Untrusted"}}})
    index = client.discover_resources()
    assert not index and index.is_partial
    assert adapter.calls == [ROOT]


def test_invalid_json_is_a_partial_failure(client_factory):
    client, _ = client_factory({ROOT: b"invalid JSON"})
    index = client.discover_resources()
    assert not index and index.is_partial
    assert "JSON object" in index.failures[0].error.message


def test_http_failure_preserves_downstream_message(client_factory):
    message = "Vendor failure: device temporarily unavailable."
    client, _ = client_factory({ROOT: (503, {"error": {"code": "Base.1.0.GeneralError", "message": message}})})
    index = client.discover_resources()
    assert index.is_partial
    assert index.failures[0].error.status_code == 503
    assert index.failures[0].error.message == message


def test_ipv6_same_origin_and_fragment_deduplication(client_factory):
    child = ROOT + "Items/1"
    client, adapter = client_factory({ROOT: document(ROOT, "ServiceRoot", Item={"@odata.id":
        "https://[2001:db8::1]:8443" + child + "#fragment"}, Duplicate={"@odata.id": child}),
        child: document(child)}, host="[2001:db8::1]:8443")
    index = client.discover_resources()
    assert len(index) == 2 and not index.is_partial
    assert adapter.calls == [ROOT, child]


def test_percent_encoded_unreserved_links_do_not_duplicate_requests(client_factory):
    child = ROOT + "Systems/1"
    client, adapter = client_factory({ROOT: document(ROOT, "ServiceRoot", First={"@odata.id": child},
        Duplicate={"@odata.id": ROOT + "%53ystems/1"}), child: document(child)})
    index = client.discover_resources()
    assert len(index) == 2 and not index.is_partial
    assert adapter.calls == [ROOT, child]
