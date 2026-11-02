"""Generic field-validation helpers.

The former aggregate validators such as validate_system() and
validate_processor() moved to model validation tags and
redfish_sdk.models.check.validate_model(). This module retains only
validate_json_key_present_but_empty() for raw offline JSON checks.
"""
from __future__ import annotations

import warnings

# ---------------------------------------------------------------------------
# Raw JSON validation for keys whose returned values are empty
# ---------------------------------------------------------------------------

def validate_json_key_present_but_empty(
    json_data: dict,
    model_class_name: str,
    odata_id: str = "",
) -> None:
    """
    Warn when a key exists in raw JSON but its value is null or empty.

    Args:
        json_data: Raw JSON dictionary.
        model_class_name: Model class name used in warning messages.
        odata_id: Resource identifier used in warning messages.
    """
    for key, value in json_data.items():
        if key.startswith("@"):
            continue  # Skip @odata.xxx metadata fields
        if value is None or (isinstance(value, str) and value.strip() == ""):
            warnings.warn(
                f"{model_class_name}.{key} is present but empty "
                f"(resource={odata_id})",
                stacklevel=2,
            )
