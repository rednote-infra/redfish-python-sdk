"""
Base OEM extractor and the generic (standard Redfish) implementation.

Each vendor's BMC exposes fan and drive readings under a different Oem
sub-key with a different casing / spelling (xFusion / Public / Lenovo /
gOemCustomeString / DiskTemperatureCelsius, ...). Rather than modelling
every vendor's private field on :class:`Bmc`, we route the read through
a vendor strategy so the model layer stays vendor-agnostic.

Two extension points are provided:

- :meth:`get_fan_speed_ratio` — normalized fan speed as percent (0-100).
- :meth:`get_drive_temperature_celsius` — drive temperature in Celsius.

The default implementations here match the standard DMTF behaviour:
:meth:`get_fan_speed_ratio` derives the ratio from
``Reading / MaxReadingRange`` (works for Lenovo / Nettrix which don't
publish an OEM ``SpeedRatio``); :meth:`get_drive_temperature_celsius`
returns ``None`` (DMTF has no top-level drive temperature).

The design mirrors ``log_collect_strategies`` and ``update_strategies``
so all three multi-vendor packages share one mental model.
"""
from __future__ import annotations

import logging
from abc import ABC
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ...models.drive import Drive
    from ...models.oem import Oem
    from ...models.thermal import Fan

logger = logging.getLogger(__name__)


class BaseOemExtractor(ABC):
    """
    Abstract base for vendor-specific OEM field extraction.

    The default methods implement the DMTF-standard behaviour. Vendors
    override only the readings whose location differs.
    """

    # ------------------------------------------------------------------
    # Fan
    # ------------------------------------------------------------------

    def get_fan_speed_ratio(self, fan: "Fan") -> Optional[float]:
        """
        Return fan speed as a percentage (0-100).

        Default: derived from ``Reading / MaxReadingRange`` — this is the
        DMTF fallback used by vendors (Lenovo / Nettrix) whose BMC does
        not publish an OEM ``SpeedRatio``.
        """
        if fan.reading is None or not fan.max_reading_range:
            return None
        try:
            return round(fan.reading / fan.max_reading_range * 100, 1)
        except (TypeError, ZeroDivisionError):
            return None

    # ------------------------------------------------------------------
    # Drive
    # ------------------------------------------------------------------

    def get_drive_temperature_celsius(self, drive: "Drive") -> Optional[float]:
        """
        Return drive temperature in Celsius, or ``None`` when unknown.

        Default: DMTF has no standard top-level drive temperature; vendors
        override this to read their OEM field.
        """
        return None


class GenericOemExtractor(BaseOemExtractor):
    """
    Fallback extractor for unrecognized vendors.

    Uses the DMTF-standard behaviour only: fan speed ratio derived from
    ``Reading / MaxReadingRange``; no drive temperature.
    """


# ----------------------------------------------------------------------
# Shared helpers for vendor strategies
# ----------------------------------------------------------------------


def read_public_field(oem: Optional["Oem"], field_alias: str) -> Any:
    """
    Read a field from ``Oem.Public`` by its original JSON alias.

    ``Public`` is modelled as :attr:`Oem.bmc` via ``alias="Public"``.
    Fields typed on :class:`Bmc` are read via the typed attribute; fields
    that are not typed fall through to :attr:`Bmc.model_extra` (pydantic
    ``extra="allow"``), so vendor-specific readings such as
    ``Public.SpeedRatio`` / ``Public.temperature`` /
    ``Public.TemperatureCelsius`` can be looked up here without adding
    per-vendor typed fields on the model.
    """
    if oem is None or oem.bmc is None:
        return None

    # Prefer the typed attribute when present (covers common OEM fields
    # such as Public.ProductName / Public.BMCVersion).
    from ...models.oem import Bmc

    for field_name, field_info in Bmc.model_fields.items():
        # Bmc uses populate_by_name=True; alias may be a single string or a
        # comma-separated list (see Bmc.build_date). Match both forms.
        alias = field_info.alias
        if alias == field_alias or (
            isinstance(alias, str) and field_alias in alias.split(",")
        ):
            value = getattr(oem.bmc, field_name, None)
            if value is not None:
                return value
            break

    extra = oem.bmc.model_extra or {}
    return extra.get(field_alias)


def read_vendor_field(
    oem: Optional["Oem"], vendor_key: str, field_alias: str
) -> Any:
    """
    Read ``Oem.<vendor_key>.<field_alias>`` from the raw payload.

    ``vendor_key`` is the JSON key as it appears on the BMC response
    (e.g. ``"xFusion"``, ``"Lenovo"``, ``"gOemCustomeString"``). These
    keys are captured in :attr:`Oem.model_extra` because they are not
    explicit fields on :class:`Oem` — the merged ``bmc`` view is a
    convenience for common fields, but vendor-specific readings are
    intentionally read from the raw sub-dict here so no vendor-specific
    typed fields need to be added to :class:`Bmc`.
    """
    if oem is None:
        return None
    extra = oem.model_extra or {}
    sub = extra.get(vendor_key)
    if not isinstance(sub, dict):
        return None
    return sub.get(field_alias)


def to_float(value: Any) -> Optional[float]:
    """
    Best-effort float coercion. BMCs report temperatures as int / float /
    numeric string (xFusion returns strings, e.g. ``"35"``). Returns
    ``None`` for empty / unparseable inputs so the caller can skip cleanly.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        # bool is a subclass of int; reject it explicitly to avoid
        # accidentally coercing ``True`` -> ``1.0``.
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
