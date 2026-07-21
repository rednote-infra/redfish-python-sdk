"""
Update strategy registry — maps vendor keys to strategy instances.

Strategies are registered at import time via register(). The registry
provides a get() method that returns the appropriate strategy for a
given vendor, falling back to GenericUpdateStrategy for unknown vendors.
"""
from __future__ import annotations

import logging
from typing import Dict

from .base import BaseUpdateStrategy, GenericUpdateStrategy

logger = logging.getLogger(__name__)

# Singleton fallback strategy
_GENERIC_STRATEGY = GenericUpdateStrategy()


class UpdateStrategyRegistry:
    """
    Registry mapping vendor keys to update strategy instances.

    Usage:
        # Registration (done at module import time)
        UpdateStrategyRegistry.register("inspur", InspurUpdateStrategy())

        # Lookup
        strategy = UpdateStrategyRegistry.get("inspur")
        response = strategy.execute(client, image_uri, ...)
    """

    _strategies: Dict[str, BaseUpdateStrategy] = {}

    @classmethod
    def register(cls, vendor: str, strategy: BaseUpdateStrategy) -> None:
        """
        Register a strategy for a vendor.

        Args:
            vendor: Canonical vendor key (lowercase, e.g., "inspur")
            strategy: Strategy instance
        """
        cls._strategies[vendor.lower()] = strategy
        logger.debug("Registered update strategy for vendor: %s", vendor)

    @classmethod
    def get(cls, vendor: str) -> BaseUpdateStrategy:
        """
        Get the update strategy for a vendor.

        Args:
            vendor: Vendor key (case-insensitive)

        Returns:
            Registered strategy, or GenericUpdateStrategy as fallback
        """
        strategy = cls._strategies.get(vendor.lower())
        if strategy is None:
            logger.warning(
                "No update strategy registered for vendor '%s', "
                "using generic Redfish strategy",
                vendor,
            )
            return _GENERIC_STRATEGY
        return strategy

    @classmethod
    def registered_vendors(cls) -> list:
        """Return the list of registered vendor keys."""
        return list(cls._strategies.keys())
