"""Public compatibility exports for shared OEM provider management."""
from .managers.oem_providers import (
    OEM_ENTRY_POINT_PREFIX,
    BaseLogCollectStrategy,
    BaseOemExtractor,
    BaseUpdateStrategy,
    OemCategory,
    OemImplementation,
    OemProviderConflictError,
    OemProviderLoadError,
    OemProviderRegistry,
)

__all__ = [
    "OEM_ENTRY_POINT_PREFIX", "OemCategory", "OemImplementation", "OemProviderRegistry",
    "OemProviderLoadError", "OemProviderConflictError",
    "BaseUpdateStrategy", "BaseLogCollectStrategy", "BaseOemExtractor",
]
