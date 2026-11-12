"""Bounded inventory exploration of standard and unknown OEM JSON resources.

Only the resource identity/type envelope has a fixed schema. Remaining properties
and nested OEM links intentionally retain their dynamic JSON representation.
"""
from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Optional, Union, overload
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from requests.utils import requote_uri

from .exceptions import RedfishException, RedfishValidationError
from .request import HttpMethod

if TYPE_CHECKING:
    from .client import RedfishClient

_ODATA_ID = "@odata.id"
_ODATA_TYPE = "@odata.type"
_NEXT_LINKS = frozenset({"Members@odata.nextLink", "@odata.nextLink"})
_TYPE_PATTERN = r"#[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)+"
_FULL_TYPE = re.compile(_TYPE_PATTERN + r"\Z")
_SHORT_TYPE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_EXPENSIVE = frozenset({
    "logservices", "logservice", "logservicecollection", "logentry", "logentrycollection",
    "telemetryservice", "metricreports", "metricreport", "metricreportcollection",
    "metricreportdefinitions", "metricreportdefinitioncollection", "metricdefinitions",
    "metricdefinitioncollection", "triggers", "triggercollection",
})
DEFAULT_DISCOVERY_MAX_DEPTH = 8
DEFAULT_DISCOVERY_MAX_RESOURCES = 256
_DEPTH_LIMIT = "max_depth"
_RESOURCE_LIMIT = "max_resources"


class _ResourceDocument(BaseModel):
    """Fixed Redfish envelope; resource-specific and OEM fields remain dynamic."""

    model_config = ConfigDict(strict=True, extra="allow")
    odata_id: str = Field(alias=_ODATA_ID, min_length=1)
    odata_type: str = Field(alias=_ODATA_TYPE, pattern=r"^" + _TYPE_PATTERN + r"$")


@dataclass(frozen=True)
class ResourceDescriptor:
    """A resource identity, full type and unmodified JSON properties.

    Properties can contain sensitive BMC data; they are excluded from repr.
    Unknown OEM types are supported without inventing a typed response model.
    """

    uri: str = field(repr=False)
    odata_type: str
    properties: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class ResourceDiscoveryFailure:
    """An HTTP, malformed-resource or rejected-link failure during traversal."""

    uri: str = field(repr=False)
    error: RedfishException


def _validate_selection(odata_type, where):
    if odata_type is not None and (not isinstance(odata_type, str) or not (
        _SHORT_TYPE.fullmatch(odata_type) or _FULL_TYPE.fullmatch(odata_type)
    )):
        raise RedfishValidationError("odata_type must be an unversioned type name or full @odata.type")
    if where is not None and (not isinstance(where, Mapping) or any(not isinstance(key, str) for key in where)):
        raise RedfishValidationError("where must map exact top-level property names to JSON values")


def _exact_json(left, right):
    """Compare JSON values without treating booleans as zero/one."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_exact_json(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_exact_json(a, b) for a, b in zip(left, right))
    return left == right


@dataclass(frozen=True)
class ResourceIndex(Sequence[ResourceDescriptor]):
    """An iterable inventory with explicit completeness and exclusion metadata.

    ``limits_reached`` identifies depth/request-budget truncation. Intentional
    subtree and expensive-resource exclusions do not make ``is_partial`` true.
    Filtering preserves all diagnostics, even when it matches no resources.
    ``types`` contains sorted, fully qualified @odata.type values.
    """

    resources: tuple[ResourceDescriptor, ...] = ()
    failures: tuple[ResourceDiscoveryFailure, ...] = ()
    limits_reached: tuple[str, ...] = ()
    excluded: tuple[str, ...] = field(default=(), repr=False)

    def __len__(self) -> int:
        return len(self.resources)

    def __iter__(self) -> Iterator[ResourceDescriptor]:
        return iter(self.resources)

    @overload
    def __getitem__(self, index: int) -> ResourceDescriptor: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[ResourceDescriptor, ...]: ...

    def __getitem__(self, index: Union[int, slice]):
        return self.resources[index]

    @property
    def is_partial(self) -> bool:
        """Return whether a failure or configured bound prevented retrieval."""
        return bool(self.failures or self.limits_reached)

    @property
    def types(self) -> tuple[str, ...]:
        """List unique discovered full OData types in deterministic order."""
        return tuple(sorted({resource.odata_type for resource in self.resources}))

    def find(self, *, odata_type: Optional[str] = None, where: Optional[Mapping[str, Any]] = None) -> ResourceIndex:
        """Select a full/unversioned type and exact top-level JSON properties.

        All supplied properties must exist and match, including explicit nulls.
        Boolean false differs from numeric zero; nested JSON values are compared
        structurally. No glob, substring matching, coercion or OData expression
        evaluation is performed. Selecting never causes additional requests.
        """
        _validate_selection(odata_type, where)
        matches = tuple(resource for resource in self.resources if (
            odata_type is None or resource.odata_type == odata_type
            or resource.odata_type.rsplit(".", 1)[-1] == odata_type
        ) and all(key in resource.properties and _exact_json(resource.properties[key], value)
                  for key, value in (where or {}).items()))
        return replace(self, resources=matches)


def _links(document):
    """Yield nested reference objects and paging links without Python recursion."""
    stack = [(iter(document.items()), False, True)]
    while stack:
        items, expensive, top = stack[-1]
        try:
            key, value = next(items)
        except StopIteration:
            stack.pop()
            continue
        blocked = expensive or isinstance(key, str) and key.casefold() in _EXPENSIVE
        if key == _ODATA_ID:
            if not top:
                yield value, blocked, False
        elif key in _NEXT_LINKS:
            yield value, blocked, True
        elif isinstance(value, dict):
            stack.append((iter(value.items()), blocked, False))
        elif isinstance(value, list):
            stack.append((iter(enumerate(value)), blocked, False))


def discover_resources(client: RedfishClient, *, start: Optional[str] = None,
                       max_depth: int = DEFAULT_DISCOVERY_MAX_DEPTH, max_resources: int = DEFAULT_DISCOVERY_MAX_RESOURCES,
                       include_expensive: bool = False) -> ResourceIndex:
    """Explore a same-origin subtree using GET only and no automatic redirects.

    Root depth is zero; nextLink pages keep the collection's depth. The resource
    budget bounds unique scheduled requests plus rejected links, including HTTP
    failures and paging requests. The queue and failure list share this budget.
    Depth/budget truncation is reported, never treated as an empty success.
    Resources are deduplicated by validated @odata.id, requests by full URI.
    Logs and telemetry are excluded by relation/path/type unless opted in.
    Timeouts/retries use the client's existing transport configuration.
    """
    for name, value, minimum in ((_DEPTH_LIMIT, max_depth, 0), (_RESOURCE_LIMIT, max_resources, 1)):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise RedfishValidationError(f"{name} must be an integer >= {minimum}")
    if not isinstance(include_expensive, bool):
        raise RedfishValidationError("include_expensive must be a boolean")
    origin = f"{client._http_client.scheme}://{client.host}"

    def resolve(link, parent):
        if (not isinstance(link, str) or not link or link.startswith("//") or "\\" in link
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in link)):
            raise RedfishValidationError("Invalid discovered resource link")
        try:
            parts = urlsplit(urljoin(origin + parent, link))
            decoded = unquote(parts.path)
            if ("\\" in decoded or any(part in {".", ".."} for part in decoded.split("/"))
                    or any(ord(c) < 32 or ord(c) == 127 for c in decoded)):
                raise ValueError("Ambiguous resource path")
            target = requote_uri(urlunsplit(parts._replace(fragment="")))
            client._http_client._resolve_url(target)
            canonical = urlsplit(target)
            return urlunsplit(("", "", canonical.path or "/", canonical.query, ""))
        except ValueError as exc:
            raise RedfishValidationError("Invalid discovered resource link") from exc

    initial = resolve(client.service_root if start is None else start, client.service_root)
    scope = unquote(urlsplit(initial).path).rstrip("/")

    def excluded_path(uri):
        decoded = unquote(urlsplit(uri).path)
        return (decoded.rstrip("/") != scope and not decoded.startswith(scope + "/")) or (
            not include_expensive and any(part.casefold() in _EXPENSIVE for part in decoded.split("/"))
        )

    queue = deque([(initial, 0)])
    seen = {initial}
    resources: dict[str, ResourceDescriptor] = {}
    failures = []
    excluded: dict[str, None] = {}
    limits = set()
    budget_used = 1
    while queue:
        uri, depth = queue.popleft()
        if excluded_path(uri):
            excluded[uri] = None
            continue
        try:
            response = client.request(HttpMethod.GET, uri)
            if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
                raise RedfishException(response.status_code, "Resource discovery requires a successful JSON response")
            if not isinstance(response.json_data, dict):
                raise RedfishValidationError("Resource discovery requires a JSON object")
            document = response.json_data
        except RedfishException as exc:
            failures.append(ResourceDiscoveryFailure(uri, exc))
            continue
        try:
            envelope = _ResourceDocument.model_validate(document)
            identity = resolve(envelope.odata_id, uri)
            expensive_type = envelope.odata_type.rsplit(".", 1)[-1].casefold() in _EXPENSIVE
            if excluded_path(identity) or (not include_expensive and expensive_type):
                excluded[uri] = None
                continue
            resources.setdefault(identity, ResourceDescriptor(identity, envelope.odata_type, document))
        except ValidationError:
            failures.append(ResourceDiscoveryFailure(
                uri, RedfishValidationError("Resource has missing or invalid @odata.id or @odata.type")
            ))
        except RedfishException as exc:
            failures.append(ResourceDiscoveryFailure(uri, exc))
            continue
        for link, expensive, paging in _links(document):
            try:
                target = resolve(link, uri)
            except RedfishException as exc:
                if budget_used >= max_resources:
                    limits.add(_RESOURCE_LIMIT)
                    break
                budget_used += 1
                failures.append(ResourceDiscoveryFailure(link if isinstance(link, str) else uri, exc))
                continue
            if target in seen:
                continue
            if excluded_path(target) or expensive and not include_expensive:
                excluded[target] = None
                continue
            next_depth = depth if paging else depth + 1
            if next_depth > max_depth:
                limits.add(_DEPTH_LIMIT)
                continue
            if budget_used >= max_resources:
                limits.add(_RESOURCE_LIMIT)
                break
            seen.add(target)
            budget_used += 1
            if paging:
                queue.appendleft((target, next_depth))
            else:
                queue.append((target, next_depth))
    return ResourceIndex(tuple(resources.values()), tuple(failures), tuple(sorted(limits)), tuple(excluded))
