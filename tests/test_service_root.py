"""Service-root configuration is shared by sync/async clients and discovery paths."""
import asyncio
import json
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
import requests

from redfish_sdk import AsyncRedfishClient, AuthenticationMode, RedfishClient, RedfishResource, RedfishValidationError
from redfish_sdk.http_client import RedfishHttpClient
from redfish_sdk.models.common import Link
from redfish_sdk.models.root import RootService

ROOT = "/gateway/redfish/v1/"


def response(status=200, payload=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload or {}).encode()
    result.headers.update(headers or {})
    return result


class Adapter(requests.adapters.BaseAdapter):
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append(request)
        result = self.handler(request)
        result.request, result.url = request, request.url
        return result

    def close(self):
        pass


def test_default_root_and_legacy_root_without_leading_slash():
    with RedfishClient("bmc.example", "user", "password", verify_ssl=True) as client:
        assert client.service_root == "/redfish/v1/"
        assert client._http_client._resolve_url("vendor/resource") == "https://bmc.example/vendor/resource"
        assert client._http_client._resolve_url("redfish/v1/Systems") == "https://bmc.example/redfish/v1/Systems"


@pytest.mark.parametrize("root", [ROOT, "/redfish/v1/"])
def test_custom_root_relative_advertised_links_and_opaque_paging(root):
    def handler(request):
        path = urlsplit(request.url).path
        if path == root:
            return response(payload={"Systems": {"@odata.id": "Systems"}})
        if path == root + "Systems":
            if urlsplit(request.url).query:
                return response(payload={"Members": [{"@odata.id": "Systems/2"}]})
            return response(payload={"Members": [{"@odata.id": "Systems/1"}],
                "Members@odata.nextLink": "?page=2&token=opaque%2Bvalue"})
        return response(payload={"Id": path.rsplit("/", 1)[-1], "Name": "Server"})
    adapter = Adapter(handler)
    with requests.Session() as session:
        session.trust_env = False
        session.mount("https://", adapter)
        with RedfishClient("bmc.example", "user", "password", session=session,
                           service_root=root.rstrip("/")) as client:
            assert client.service_root == root
            assert [system.id for system in client.get_systems()] == ["1", "2"]
    assert [request.url.removeprefix("https://bmc.example") for request in adapter.calls] == [
        root, root + "Systems", root + "Systems/1", root + "Systems?page=2&token=opaque%2Bvalue", root + "Systems/2"]


@pytest.mark.parametrize("prefix", [None, "", "redfish/v1", "//other.example/", "https://other.example/",
    "/path?query=1", "/path#fragment", "/a/../b", "/a/%2e%2e/b", "/a\\b", "/path\n"])
def test_malformed_root_rejected_before_any_request(prefix):
    with pytest.raises(RedfishValidationError):
        RedfishClient("bmc.example", "user", "password", service_root=prefix)


def test_fallbacks_and_resource_lookup_use_custom_root(monkeypatch):
    with RedfishClient("bmc.example", "user", "password", verify_ssl=True, service_root=ROOT) as client:
        root = RootService.model_construct(chassis=Link.model_construct())
        monkeypatch.setattr(client, "_get_root", lambda: root)
        assert client._get_chassis_collection_odata_id() == ROOT + "Chassis"
        typed_get = Mock()
        monkeypatch.setattr(client._http_client, "get", typed_get)
        client._get_task_service()
        assert typed_get.call_args.args[0] == ROOT + "TaskService"
        get_raw = Mock(return_value={"Systems": {"@odata.id": "Systems"}})
        monkeypatch.setattr(client._http_client, "get_raw", get_raw)
        assert client.get_odata_id(RedfishResource.SYSTEMS) == "Systems"
        assert get_raw.call_args.args[0] == ROOT


def test_default_session_refresh_endpoint_uses_configured_root():
    with RedfishHttpClient("bmc.example", "user", "password", service_root=ROOT,
                           verify_ssl=True, auth_mode=AuthenticationMode.SESSION) as client:
        client._external_session.post = Mock(return_value=response(201, headers={"X-Auth-Token": "example"}))
        client._session.get = Mock(return_value=response())
        client.get_raw("Systems/1")
        assert client._external_session.post.call_args.args[0] == "https://bmc.example" + ROOT + "SessionService/Sessions"
        assert client._session.get.call_args.args[0] == "https://bmc.example" + ROOT + "Systems/1"


def test_same_origin_absolute_links_are_preserved_and_foreign_targets_rejected():
    with RedfishHttpClient("[2001:db8::1]:8443", "user", "password", service_root=ROOT, verify_ssl=True) as client:
        assert client._resolve_url("Systems/1") == "https://[2001:db8::1]:8443" + ROOT + "Systems/1"
        assert client._resolve_url("/other/Systems") == "https://[2001:db8::1]:8443/other/Systems"
        for path in ("https://other.example/root", "//other.example/root", "http://[2001:db8::1]:8443/root", "https://[invalid]/root"):
            with pytest.raises(RedfishValidationError):
                client.request("GET", path)


def test_async_root_discovery_fallback_and_relative_requests():
    adapter = Adapter(lambda request: response(201, headers={"X-Auth-Token": "example", "Location": ROOT + "SessionService/Sessions/1"})
        if request.method == "POST" else response(204) if request.method == "DELETE" else response())
    async def run():
        with requests.Session() as session:
            session.trust_env = False
            session.mount("https://", adapter)
            async with AsyncRedfishClient("bmc.example", "user", "password", session=session, service_root=ROOT) as client:
                assert client.service_root == ROOT
                await client.get("Systems/1")
    asyncio.run(run())
    assert [urlsplit(request.url).path for request in adapter.calls] == [
        ROOT, ROOT + "SessionService/Sessions", ROOT + "Systems/1", ROOT + "SessionService/Sessions/1"]


def test_async_default_root_preserves_legacy_bare_request_paths():
    with requests.Session() as session:
        client = AsyncRedfishClient("bmc.example", "user", "password", session=session)
        assert client._url("vendor/resource") == "https://bmc.example/vendor/resource"
