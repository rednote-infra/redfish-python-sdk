"""Retry policies used by the Redfish transport."""

from enum import Enum


class RetryPolicy(str, Enum):
    """Per-operation policy controlling whether a write may be replayed."""

    DEFAULT = "default"
    IDEMPOTENT = "idempotent"
