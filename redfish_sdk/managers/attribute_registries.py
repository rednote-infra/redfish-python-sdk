"""Discovery and bounded caching for Attribute Registry documents only."""
from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Optional

from ..exceptions import RedfishException, RegistryResolutionError
from ..models.attribute_registry import AttributeRegistry
from .registries import _MAX_CACHE_ENTRIES, _REGISTRY_NAME

if TYPE_CHECKING:
    from ..client import RedfishClient


class AttributeRegistriesManager:
    def __init__(self, client: RedfishClient):
        self._registries = client._registries
        self._document_cache: OrderedDict[str, AttributeRegistry] = OrderedDict()

    def get(self, registry_id: str, language: Optional[str] = None) -> AttributeRegistry:
        """Resolve an advertised Id, Registry name, or resource URI.

        Full numeric versions are pinned; Major.Minor selects the highest
        advertised errata in that family. Bare names choose the highest offered
        version. Opaque vendor IDs require an exact match. No URI is fabricated.
        Language priority is exact, primary, English, then lexical location.
        Returned models are copies so edits cannot poison later validation.
        """
        registry = self._find(registry_id, language)
        locations = sorted(registry.location or [], key=lambda item: self._language_rank(item, language))
        if not locations:
            raise RegistryResolutionError("Attribute registry has no advertised locations")
        location = locations[0]
        sources = list(dict.fromkeys(source for source in (location.uri, location.publication_uri) if source))
        if not sources:
            raise RegistryResolutionError("Attribute registry location has no Uri or PublicationUri")
        last_error = None
        for source in sources:
            try:
                document = self._document_cache.get(source)
                if document is None:
                    document = self._registries._fetch_document(source, AttributeRegistry)
                self._check_metadata(document, registry, location)
            except RedfishException:
                # Preserve downstream messages, including authentication failures.
                raise
            except (ValueError, OSError) as exc:
                last_error = exc
                continue
            self._document_cache[source] = document
            self._document_cache.move_to_end(source)
            while len(self._document_cache) > _MAX_CACHE_ENTRIES:
                self._document_cache.popitem(last=False)
            return document.model_copy(deep=True)
        raise RegistryResolutionError("No advertised location supplied a compatible AttributeRegistry document") from last_error

    def clear_cache(self) -> None:
        self._document_cache.clear()

    def _find(self, reference: str, language: Optional[str]):
        if not isinstance(reference, str) or not reference.strip():
            raise RegistryResolutionError("An advertised attribute registry reference is required")
        requested = _REGISTRY_NAME.fullmatch(reference)
        candidates = []
        for registry in self._registries.registries():
            if registry.odata_id == reference:
                return registry
            try:
                prefix, version = self._registries._registry_parts(registry)
            except RegistryResolutionError:
                if reference in (registry.id, registry.registry_prefix):
                    candidates.append(((0, 0, 0), str(registry.id or ""), registry))
                continue
            if requested:
                if prefix.casefold() != requested.group("prefix").casefold():
                    continue
                required = self._registries._matched_version(requested)
                if version[:2] != required[:2] or (requested.group("errata") is not None and version != required):
                    continue
            elif reference not in (registry.id, registry.registry_prefix) and reference.casefold() != prefix.casefold():
                continue
            candidates.append((version, str(registry.id or ""), registry))
        if not candidates:
            raise RegistryResolutionError("The requested attribute registry/version is not advertised")
        # Choose locale across RegistryFiles too: vendors can publish one file
        # per language with the same Registry reference and different Ids.
        candidates.sort(key=lambda entry: (
            tuple(-part for part in entry[0]),
            min((self._language_rank(location, language) for location in entry[2].location or []),
                default=(4, "", "", "")),
            entry[1], entry[2].odata_id or "",
        ))
        return candidates[0][2]

    @staticmethod
    def _language_rank(location, language):
        candidate = (location.language or "").casefold()
        requested = (language or "").casefold()
        if not location.uri and not location.publication_uri:
            rank = 5
        elif requested and candidate == requested:
            rank = 0
        elif requested and candidate and candidate.split("-", 1)[0] == requested.split("-", 1)[0]:
            rank = 1
        elif candidate == "en":
            rank = 2
        else:
            rank = 3
        return rank, candidate, location.uri or "", location.publication_uri or ""

    def _check_metadata(self, document, registry, location):
        try:
            _, expected = self._registries._registry_parts(registry)
        except RegistryResolutionError:
            expected = None
        if document.registry_version is not None:
            actual = self._registries._parse_version(document.registry_version)
            if actual is None or (expected is not None and actual != expected):
                raise ValueError("Attribute registry version differs from advertised metadata")
        if document.language and location.language and document.language.casefold() != location.language.casefold():
            raise ValueError("Attribute registry language differs from advertised metadata")
