"""Shared helpers for constructing presence-aware request models."""

from __future__ import annotations

from typing import Any, Dict


def compact_optional_fields(**fields: Any) -> Dict[str, Any]:
    """Return manager arguments that were supplied with non-null values."""
    return {name: value for name, value in fields.items() if value is not None}
