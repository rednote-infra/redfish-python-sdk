"""Redfish registry-file discovery and message-registry resolution."""
from __future__ import annotations

import logging
import re
from collections import OrderedDict
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import requests

from ..exceptions import RegistryResolutionError
from ..models.registry import (
    MessageRegistry,
    Registry,
    RegistryLocation,
    RegistryMessage,
    ResolvedMessage,
)
from .system_resources import select_member

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)

_MESSAGE_ID = re.compile(
    r"^(?P<prefix>[^.]+)\.(?P<major>\d+)\.(?P<minor>\d+)\.(?P<key>[^.]+)$"
)
_REGISTRY_NAME = re.compile(
    r"^(?P<prefix>[^.]+)\.(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<errata>\d+))?$"
)
_ARGUMENT = re.compile(r"%(\d+)")
_MAX_CACHE_ENTRIES = 32


class RegistriesManager:
    """Manage RegistryFile resources and resolve complete registry messages."""

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client
        self._document_cache: OrderedDict[str, MessageRegistry] = OrderedDict()

    def registries(self) -> List[Registry]:
        """Return the RegistryFile resources advertised by the service."""
        return self._client._get_registries_collection()

    def get(self, registry_id: str) -> Registry:
        """Return a RegistryFile resource by advertised Id or ``@odata.id``."""
        return select_member(self.registries(), registry_id)

    def resolve(
        self,
        message_id: str,
        message_args: Optional[Sequence[object]] = None,
        language: Optional[str] = None,
    ) -> ResolvedMessage:
        """Resolve a MessageId through the registries advertised by the BMC."""
        match = _MESSAGE_ID.fullmatch(message_id)
        if not match:
            raise RegistryResolutionError(
                f"Invalid MessageId {message_id!r}; expected Prefix.Major.Minor.MessageKey"
            )

        prefix = match.group("prefix")
        version = (int(match.group("major")), int(match.group("minor")))
        key = match.group("key")
        registry = self._find_registry(prefix, version)
        return self._resolve_from_registry(
            registry,
            key,
            requested_message_id=message_id,
            message_args=message_args,
            language=language,
            trail=(),
        )

    def clear_cache(self) -> None:
        """Discard cached message-registry documents."""
        self._document_cache.clear()

    def _resolve_from_registry(
        self,
        registry: Registry,
        key: str,
        *,
        requested_message_id: str,
        message_args: Optional[Sequence[object]],
        language: Optional[str],
        trail: Tuple[str, ...],
    ) -> ResolvedMessage:
        identity = self._registry_identity(registry)
        step = f"{identity}:{key}"
        if step in trail:
            chain = " -> ".join((*trail, step))
            raise RegistryResolutionError(
                f"Message registry reference cycle detected: {chain}"
            )

        document = self._load_document(registry, language)
        next_trail = (*trail, step)
        if document.referenced_registry:
            source = self._find_referenced_registry(document.referenced_registry)
            return self._resolve_from_registry(
                source,
                key,
                requested_message_id=requested_message_id,
                message_args=message_args,
                language=language,
                trail=next_trail,
            )

        definition = document.messages.get(key)
        if definition is None:
            raise RegistryResolutionError(
                f"Message key {key!r} is not present in registry {identity}"
            )
        if definition.referenced_registry:
            source = self._find_referenced_registry(definition.referenced_registry)
            return self._resolve_from_registry(
                source,
                key,
                requested_message_id=requested_message_id,
                message_args=message_args,
                language=language,
                trail=next_trail,
            )

        return self._resolved_message(
            document,
            registry,
            key,
            definition,
            requested_message_id,
            message_args,
        )

    def _resolved_message(
        self,
        document: MessageRegistry,
        registry: Registry,
        key: str,
        definition: RegistryMessage,
        requested_message_id: str,
        message_args: Optional[Sequence[object]],
    ) -> ResolvedMessage:
        if definition.message is None:
            raise RegistryResolutionError(
                f"Message {key!r} in registry {self._registry_identity(registry)} has no Message text"
            )

        args = [str(value) for value in message_args] if message_args is not None else []
        expected = definition.number_of_args
        if message_args is not None and expected is not None and len(args) != expected:
            raise RegistryResolutionError(
                f"Message {key!r} requires {expected} argument(s), got {len(args)}"
            )

        text = definition.message
        if message_args is not None:

            def substitute(match: re.Match[str]) -> str:
                index = int(match.group(1)) - 1
                if index < 0 or index >= len(args):
                    raise RegistryResolutionError(
                        f"Message {key!r} references missing argument %{index + 1}"
                    )
                return args[index]

            text = _ARGUMENT.sub(substitute, text)

        prefix, version = self._document_identity(document, registry)
        major, minor, _ = version
        source_message_id = f"{prefix}.{major}.{minor}.{key}"
        return ResolvedMessage(
            requested_message_id=requested_message_id,
            message_id=source_message_id,
            registry_prefix=prefix,
            registry_version=".".join(str(part) for part in version),
            message_key=key,
            message=text,
            message_args=args,
            message_severity=definition.message_severity,
            resolution=definition.resolution,
        )

    def _find_registry(self, prefix: str, version: Tuple[int, int]) -> Registry:
        registries = self.registries()
        candidates = []
        for registry in registries:
            try:
                registry_prefix, registry_version = self._registry_parts(registry)
            except RegistryResolutionError:
                continue
            if (
                registry_prefix.casefold() == prefix.casefold()
                and registry_version[:2] == version
            ):
                candidates.append((registry_version, registry))
        if not candidates:
            available = []
            for item in registries:
                try:
                    available.append(self._registry_parts(item)[0])
                except RegistryResolutionError:
                    continue
            raise RegistryResolutionError(
                f"Unknown registry prefix or version {prefix}.{version[0]}.{version[1]}; "
                f"available prefixes: {sorted(set(available))}"
            )
        return max(candidates, key=lambda item: item[0])[1]

    def _find_referenced_registry(self, reference: str) -> Registry:
        parsed = _REGISTRY_NAME.fullmatch(reference)
        if not parsed:
            for registry in self.registries():
                if str(registry.id) == reference:
                    return registry
            raise RegistryResolutionError(
                f"Referenced registry {reference!r} is not advertised by the service"
            )

        prefix = parsed.group("prefix")
        major = int(parsed.group("major"))
        minor = int(parsed.group("minor"))
        errata = parsed.group("errata")
        candidates = []
        for registry in self.registries():
            try:
                registry_prefix, version = self._registry_parts(registry)
            except RegistryResolutionError:
                continue
            if registry_prefix.casefold() != prefix.casefold() or version[:2] != (major, minor):
                continue
            if errata is not None and version[2] != int(errata):
                continue
            candidates.append((version, registry))
        if not candidates:
            raise RegistryResolutionError(
                f"Referenced registry {reference!r} is not advertised by the service"
            )
        return max(candidates, key=lambda item: item[0])[1]

    def _load_document(
        self, registry: Registry, language: Optional[str]
    ) -> MessageRegistry:
        location = self._select_location(registry, language)
        sources = [source for source in (location.uri, location.publication_uri) if source]
        if not sources:
            raise RegistryResolutionError(
                f"Registry {self._registry_identity(registry)} has no usable Uri or PublicationUri"
            )

        failures = []
        for source in dict.fromkeys(sources):
            cached = self._document_cache.get(source)
            if cached is not None:
                self._document_cache.move_to_end(source)
                return cached
            try:
                document = self._fetch_document(source)
            except Exception as exc:
                failures.append(f"{source}: {exc}")
                continue
            self._document_cache[source] = document
            self._document_cache.move_to_end(source)
            while len(self._document_cache) > _MAX_CACHE_ENTRIES:
                self._document_cache.popitem(last=False)
            return document

        raise RegistryResolutionError(
            f"Unable to load registry document for {self._registry_identity(registry)}: "
            + "; ".join(failures)
        )

    def _fetch_document(self, source: str) -> MessageRegistry:
        parsed = urlsplit(source)
        if not parsed.scheme or self._is_bmc_url(parsed):
            path = source
            if parsed.scheme:
                path = parsed.path or "/"
                if parsed.query:
                    path = f"{path}?{parsed.query}"
            return self._http.get(path, MessageRegistry)

        # Never reuse the authenticated BMC session for a publication host.
        session = requests.Session()
        session.trust_env = False
        session.headers.clear()
        session.cookies.clear()
        try:
            response = session.get(
                source,
                headers={"Accept": "application/json"},
                timeout=(self._http.connect_timeout, self._http.read_timeout),
            )
            response.raise_for_status()
            return MessageRegistry.model_validate(response.json())
        finally:
            session.close()

    def _is_bmc_url(self, parsed) -> bool:
        bmc = urlsplit(f"{self._http.scheme}://{self._http.host}")
        return (
            parsed.scheme.casefold() == bmc.scheme.casefold()
            and parsed.netloc.casefold() == bmc.netloc.casefold()
        )

    def _select_location(
        self, registry: Registry, language: Optional[str]
    ) -> RegistryLocation:
        locations = registry.location or []
        if not locations:
            raise RegistryResolutionError(
                f"Registry {self._registry_identity(registry)} has no locations"
            )

        if language:
            requested = language.casefold()
            for location in locations:
                if location.language and location.language.casefold() == requested:
                    return location
            primary = requested.split("-", 1)[0]
            for location in locations:
                if location.language and location.language.casefold().split("-", 1)[0] == primary:
                    return location
        for location in locations:
            if location.language and location.language.casefold() == "en":
                return location
        return locations[0]

    def _registry_parts(self, registry: Registry) -> Tuple[str, Tuple[int, int, int]]:
        explicit_version = self._parse_version(registry.registry_version)
        registry_name = _REGISTRY_NAME.fullmatch(registry.registry_prefix or "")
        resource_id = _REGISTRY_NAME.fullmatch(str(registry.id or ""))
        prefix = (
            registry_name.group("prefix")
            if registry_name
            else registry.registry_prefix
            or (resource_id.group("prefix") if resource_id else None)
        )
        if explicit_version and prefix:
            return prefix, explicit_version
        if resource_id and prefix.casefold() == resource_id.group("prefix").casefold():
            return prefix, self._matched_version(resource_id)
        if registry_name:
            return prefix, self._matched_version(registry_name)
        raise RegistryResolutionError(
            f"Registry resource {registry.id!r} has no parseable prefix and version"
        )

    @staticmethod
    def _matched_version(match: re.Match[str]) -> Tuple[int, int, int]:
        return (
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("errata") or 0),
        )

    @staticmethod
    def _parse_version(value: Optional[str]) -> Optional[Tuple[int, int, int]]:
        if not value:
            return None
        parts = value.split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            return None
        return int(parts[0]), int(parts[1]), int(parts[2])

    def _registry_identity(self, registry: Registry) -> str:
        prefix, version = self._registry_parts(registry)
        return f"{prefix}.{version[0]}.{version[1]}.{version[2]}"

    def _document_identity(
        self, document: MessageRegistry, registry: Registry
    ) -> Tuple[str, Tuple[int, int, int]]:
        fallback_prefix, fallback_version = self._registry_parts(registry)
        version = self._parse_version(document.registry_version) or fallback_version
        return document.registry_prefix or fallback_prefix, version
