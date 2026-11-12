"""Versioned, client-scoped OEM extension interfaces and lazy discovery.

External providers run trusted Python code in-process and receive the client
with its transport privileges. This is not a security sandbox.
"""
from __future__ import annotations

import logging
from enum import Enum
from importlib import metadata
from threading import RLock
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, Union

from .exceptions import RedfishValidationError
from .managers.log_collect_strategies import BaseLogCollectStrategy, LogCollectStrategyRegistry
from .managers.oem_extractors import BaseOemExtractor, OemExtractorRegistry
from .managers.update_strategies import BaseUpdateStrategy, UpdateStrategyRegistry

logger = logging.getLogger(__name__)
OEM_ENTRY_POINT_PREFIX = "redfish_sdk.oem.v1"


class OemCategory(str, Enum):
    UPDATE = "update"
    LOG_COLLECT = "log_collect"
    EXTRACTOR = "extractor"


OemImplementation = Union[BaseUpdateStrategy, BaseLogCollectStrategy, BaseOemExtractor]
_INTERFACES = {
    OemCategory.UPDATE: (BaseUpdateStrategy, UpdateStrategyRegistry),
    OemCategory.LOG_COLLECT: (BaseLogCollectStrategy, LogCollectStrategyRegistry),
    OemCategory.EXTRACTOR: (BaseOemExtractor, OemExtractorRegistry),
}
_GROUPS = {f"{OEM_ENTRY_POINT_PREFIX}.{category.value}": category for category in OemCategory}


class OemProviderLoadError(RedfishValidationError):
    """A selected optional provider could not be discovered or initialized."""


class OemProviderConflictError(OemProviderLoadError):
    """More than one provider registered the same category/vendor pair."""


def _installed_entry_points():
    points = metadata.entry_points()
    # Python 3.9 returns a mapping; newer Python returns selectable EntryPoints.
    if hasattr(points, "select"):
        return [point for group in _GROUPS for point in points.select(group=group)]
    return [point for group in _GROUPS for point in points.get(group, ())]


class OemProviderRegistry:
    """Resolve explicit > built-in > discovered providers, then generic fallback.

    allow_builtin_overrides opts into explicit > discovered > built-in instead.
    Factories load only for a selected key. Duplicate discovery entries fail
    that key without importing either; unrelated vendors remain available.
    Existing global built-in registry APIs are not modified.
    """

    def __init__(
        self, *, discover: bool = True,
        entry_points: Optional[Callable[[], Iterable[Any]]] = None,
        allow_builtin_overrides: bool = False,
    ):
        self.discover = discover
        self.allow_builtin_overrides = allow_builtin_overrides
        self._entry_points = entry_points if entry_points is not None else _installed_entry_points
        self._explicit: Dict[Tuple[OemCategory, str], OemImplementation] = {}
        self._loaded: Dict[Tuple[OemCategory, str], OemImplementation] = {}
        self._entries: Dict[Tuple[OemCategory, str], list] = {}
        self._failures: Dict[Tuple[OemCategory, str], OemProviderLoadError] = {}
        self._discovered = False
        self._discovery_error: Optional[OemProviderLoadError] = None
        self._lock = RLock()

    @staticmethod
    def _key(category: OemCategory, vendor: str):
        try:
            category = OemCategory(category)
        except ValueError as exc:
            raise RedfishValidationError("Unknown OEM provider category") from exc
        if not isinstance(vendor, str) or not vendor.strip():
            raise RedfishValidationError("OEM vendor must be a non-empty string")
        return category, vendor.strip().lower()

    def register(self, category: OemCategory, vendor: str, provider: OemImplementation) -> None:
        """Register an explicit instance; duplicate explicit keys are errors."""
        key = self._key(category, vendor)
        if not isinstance(provider, _INTERFACES[key[0]][0]):
            raise RedfishValidationError("OEM provider must implement the category's base interface")
        with self._lock:
            if key in self._explicit:
                raise OemProviderConflictError(f"Duplicate explicit OEM provider: {key[0].value}/{key[1]}")
            self._explicit[key] = provider

    def get(self, category: OemCategory, vendor: str) -> OemImplementation:
        """Get a provider without modifying the SDK's built-in registries."""
        key = self._key(category, vendor)
        with self._lock:
            if key in self._explicit:
                return self._explicit[key]
            _, builtin = _INTERFACES[key[0]]
            if not self.allow_builtin_overrides and key[1] in builtin.registered_vendors():
                return builtin.get(key[1])
            if self.discover:
                self._discover()
                if self._discovery_error:
                    if key[1] in builtin.registered_vendors():
                        return builtin.get(key[1])
                    raise self._discovery_error
                if key in self._failures:
                    raise self._failures[key]
                if key in self._loaded:
                    return self._loaded[key]
                entries = self._entries.get(key, [])
                if len(entries) > 1:
                    error = OemProviderConflictError(f"Multiple installed OEM providers: {key[0].value}/{key[1]}")
                    self._failures[key] = error
                    logger.warning("%s", error)
                    raise error
                if entries:
                    point = entries[0]
                    try:
                        loaded = point.load()
                        provider = loaded if isinstance(loaded, _INTERFACES[key[0]][0]) else loaded()
                        if not isinstance(provider, _INTERFACES[key[0]][0]):
                            raise TypeError("OEM provider does not implement its base interface")
                    except Exception as exc:
                        error = OemProviderLoadError(
                            f"Cannot load OEM provider {key[0].value}/{key[1]} from {point.value}: {type(exc).__name__}"
                        )
                        self._failures[key] = error
                        logger.warning("%s", error)
                        raise error from exc
                    self._loaded[key] = provider
                    return provider
            return builtin.get(key[1])

    def _discover(self):
        if self._discovered:
            return
        self._discovered = True
        try:
            for point in self._entry_points():
                category = _GROUPS.get(point.group)
                if category is not None:
                    key = self._key(category, point.name)
                    self._entries.setdefault(key, []).append(point)
        except Exception as exc:
            self._discovery_error = OemProviderLoadError(f"Cannot enumerate optional OEM entry points: {type(exc).__name__}")
            logger.warning("%s", self._discovery_error)


__all__ = [
    "OEM_ENTRY_POINT_PREFIX", "OemCategory", "OemProviderRegistry", "OemProviderLoadError", "OemProviderConflictError",
    "BaseUpdateStrategy", "BaseLogCollectStrategy", "BaseOemExtractor",
]
