"""
Log-collect strategy registry — maps vendor keys to strategy instances.

Strategies are registered at import time via :meth:`register`. The registry
returns the appropriate strategy for a given vendor, falling back to
:class:`GenericLogCollectStrategy` for unknown vendors.
"""
from __future__ import annotations

import logging
from typing import Dict

from .base import BaseLogCollectStrategy, GenericLogCollectStrategy

logger = logging.getLogger(__name__)

# Singleton fallback strategy
_GENERIC_STRATEGY = GenericLogCollectStrategy()


class LogCollectStrategyRegistry:
    """
    Registry mapping vendor keys to log-collect strategy instances.

    Usage:
        # Registration (done at module import time)
        LogCollectStrategyRegistry.register("xfusion", XFusionLogCollectStrategy())

        # Lookup
        strategy = LogCollectStrategyRegistry.get("xfusion")
        body = strategy.build_body(diagnostic_data_type=None)
    """

    _strategies: Dict[str, BaseLogCollectStrategy] = {}

    @classmethod
    def register(cls, vendor: str, strategy: BaseLogCollectStrategy) -> None:
        """
        Register a strategy for a vendor.

        Args:
            vendor: Canonical vendor key (lowercase, e.g., "xfusion")
            strategy: Strategy instance
        """
        cls._strategies[vendor.lower()] = strategy
        logger.debug("Registered log-collect strategy for vendor: %s", vendor)

    @classmethod
    def get(cls, vendor: str) -> BaseLogCollectStrategy:
        """
        Get the log-collect strategy for a vendor.

        Args:
            vendor: Vendor key (case-insensitive)

        Returns:
            Registered strategy, or GenericLogCollectStrategy as fallback
        """
        strategy = cls._strategies.get(vendor.lower())
        if strategy is None:
            logger.warning(
                "No log-collect strategy registered for vendor '%s', "
                "using generic Redfish strategy",
                vendor,
            )
            return _GENERIC_STRATEGY
        return strategy

    @classmethod
    def registered_vendors(cls) -> list:
        """Return the list of registered vendor keys."""
        return list(cls._strategies.keys())
