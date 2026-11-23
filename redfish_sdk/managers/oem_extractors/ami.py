"""AMI MegaRAC inlet history resource placement."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .base import BaseOemExtractor

if TYPE_CHECKING:
    from ...models.thermal import Thermal

AMI_OEM_KEY = "Ami"
AMI_OEM_VENDOR = AMI_OEM_KEY.lower()
INLET_HISTORY_RESOURCE = "InletHistoryTemperature"
AMI_INLET_HISTORY_SUFFIX = f"/Oem/{AMI_OEM_KEY}/{INLET_HISTORY_RESOURCE}"


class AmiOemExtractor(BaseOemExtractor):
    """Use the AMI history endpoint while retaining default fan/drive behavior."""

    @staticmethod
    def matches_thermal(thermal: Thermal) -> bool:
        """Identify AMI firmware from this resource, independently of server make."""
        extra = thermal.oem.model_extra if thermal.oem is not None else None
        return isinstance((extra or {}).get(AMI_OEM_KEY), dict)

    def get_inlet_history_temperature_uri(self, thermal: Thermal) -> Optional[str]:
        """Derive the AMI URI from the actual Thermal URI, including custom roots."""
        if not thermal.odata_id:
            return None
        return thermal.odata_id.rstrip("/") + AMI_INLET_HISTORY_SUFFIX
