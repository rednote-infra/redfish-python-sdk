"""Optional system resources discovered strictly through advertised links."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple, TypeVar

from ..exceptions import RedfishNotFoundError, RedfishValidationError
from ..models.actions import ActionInfo
from ..models.common import Entity, RedfishResponse
from ..models.memory import Memory
from ..models.network_adapter import NetworkAdapter
from ..models.system_resources import (
    MemoryChunks,
    MemoryDomain,
    MemoryMetrics,
    NetworkInterface,
    NetworkPort,
    ResetKeysRequest,
    SecureBoot,
    SecureBootActions,
    SecureBootPatch,
)

if TYPE_CHECKING:
    from ..client import RedfishClient

SystemMember = TypeVar("SystemMember", bound=Entity)


def require_link(resource: Entity, field: str) -> str:
    link = getattr(resource, field, None)
    if not link or not link.odata_id:
        alias = type(resource).model_fields[field].alias
        raise RedfishNotFoundError(f"{type(resource).__name__} does not advertise {alias}")
    return link.odata_id


def select_member(
    resources: List[SystemMember],
    identifier: Optional[str],
    *,
    aliases: Tuple[str, ...] = (),
) -> SystemMember:
    """Select an advertised member by Id, @odata.id, or explicit aliases."""
    matches = resources if identifier is None else [
        resource
        for resource in resources
        if resource.id == identifier
        or resource.odata_id == identifier
        or any(getattr(resource, alias, None) == identifier for alias in aliases)
    ]
    if not matches:
        raise RedfishNotFoundError(f"No resource with Id or @odata.id {identifier!r}")
    if len(matches) > 1:
        raise RedfishValidationError("Multiple resources match; specify a unique @odata.id")
    return matches[0]


def unique_members(resources: List[SystemMember]) -> List[SystemMember]:
    seen = set()
    result = []
    for resource in resources:
        if resource.odata_id and resource.odata_id in seen:
            continue
        seen.add(resource.odata_id)
        result.append(resource)
    return result


class SystemResourcesManager:
    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def secure_boot(self, system_id: Optional[str] = None) -> SecureBoot:
        system = self._client._systems.get(system_id)
        return self._http.get(require_link(system, "secure_boot"), SecureBoot)

    def update_secure_boot(self, enabled: bool, system_id: Optional[str] = None) -> RedfishResponse:
        resource = self.secure_boot(system_id)
        if not resource.odata_id:
            raise RedfishNotFoundError("SecureBoot does not advertise @odata.id")
        allowed = (resource.model_extra or {}).get("SecureBootEnable@Redfish.AllowableValues")
        if allowed is not None and enabled not in allowed:
            raise RedfishValidationError(f"Unsupported SecureBootEnable {enabled!r}; advertised values: {allowed}")
        body = SecureBootPatch(secure_boot_enable=enabled, odata_etag=resource.odata_etag)
        return self._http.patch(resource.odata_id, RedfishResponse, body)

    def reset_secure_boot_keys(self, reset_keys_type: str, system_id: Optional[str] = None) -> RedfishResponse:
        resource = self.secure_boot(system_id)
        action = SecureBootActions.model_validate(resource.actions or {}).reset_keys
        if not action or not action.target:
            raise RedfishValidationError("SecureBoot does not advertise #SecureBoot.ResetKeys with a target")
        allowed = action.reset_keys_type_allowable_values
        if allowed is None and action.action_info:
            info = self._http.get(action.action_info, ActionInfo)
            allowed = info.allowable_values(ResetKeysRequest.model_fields["reset_keys_type"].alias)
        if allowed is None:
            allowed = ["ResetAllKeysToDefault", "DeleteAllKeys", "DeletePK"]
        if reset_keys_type not in allowed:
            raise RedfishValidationError(f"Unsupported ResetKeysType {reset_keys_type!r}; allowable values: {allowed}")
        return self._http.post(action.target, RedfishResponse, body=ResetKeysRequest(reset_keys_type=reset_keys_type))

    def network_interfaces(self, system_id: Optional[str] = None) -> List[NetworkInterface]:
        system = self._client._systems.get(system_id)
        return self._client._get_collection(require_link(system, "network_interfaces"), NetworkInterface)

    def network_ports(
        self, network_interface_id: Optional[str] = None, system_id: Optional[str] = None
    ) -> List[NetworkPort]:
        interfaces = self.network_interfaces(system_id)
        if network_interface_id is not None:
            interfaces = [select_member(interfaces, network_interface_id)]
        result = []
        advertised = False
        for interface in interfaces:
            link = interface.network_ports
            adapter_link = interface.links and interface.links.network_adapter
            if (not link or not link.odata_id) and adapter_link and adapter_link.odata_id:
                adapter = self._http.get(adapter_link.odata_id, NetworkAdapter)
                link = adapter.network_ports
            if link and link.odata_id:
                advertised = True
                result.extend(self._client._get_collection(link.odata_id, NetworkPort))
        if not advertised:
            raise RedfishNotFoundError("NetworkInterfaces do not advertise NetworkPorts")
        return unique_members(result)

    def memory_domains(self, system_id: Optional[str] = None) -> List[MemoryDomain]:
        system = self._client._systems.get(system_id)
        return self._client._get_collection(require_link(system, "memory_domains"), MemoryDomain)

    def memory_chunks(
        self, memory_domain_id: Optional[str] = None, system_id: Optional[str] = None
    ) -> List[MemoryChunks]:
        domains = self.memory_domains(system_id)
        if memory_domain_id is not None:
            domains = [select_member(domains, memory_domain_id)]
        result = []
        advertised = False
        for domain in domains:
            link = domain.memory_chunks
            if link and link.odata_id:
                advertised = True
                result.extend(self._client._get_collection(link.odata_id, MemoryChunks))
        if not advertised:
            raise RedfishNotFoundError("MemoryDomains do not advertise MemoryChunks")
        return unique_members(result)

    def memory_metrics(self, memory_id: Optional[str] = None, system_id: Optional[str] = None) -> MemoryMetrics:
        system = self._client._systems.get(system_id)
        memories = self._client._get_collection(require_link(system, "memory"), Memory)
        memory = select_member(memories, memory_id)
        return self._http.get(require_link(memory, "metrics"), MemoryMetrics)
