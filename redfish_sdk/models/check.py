"""
Annotation-based validation engine for the model layer.

Provides a custom Field() wrapper and a generic validate_model() function,
using declarative struct-tag-style rules similar to Go playground/validator.

Usage:
    # Model definition (replaces from pydantic import Field)
    from redfish_sdk.models.check import Field

    class Processor(Entity):
        manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="required,type=str")
        total_cores:  Optional[int] = Field(None, alias="TotalCores",   validate="required,type=int,gt=0")

    # Validation (called from tests)
    from redfish_sdk.models.check import validate_model
    validate_model(processor_instance)
"""
from __future__ import annotations

import warnings
from typing import Any

from pydantic import BaseModel
from pydantic import Field as _PydanticField

# ---------------------------------------------------------------------------
# Custom Field() wrapper
# ---------------------------------------------------------------------------

def Field(default=None, *, alias=None, validate=None, **kwargs):
    """
    Enhanced Pydantic Field wrapper with a validate parameter.

    Uses the same interface as Field and additionally supports validation tags:
        Field(None, alias="Manufacturer", validate="required,type=str")

    The validation string is stored in json_schema_extra and read by
    validate_model() at runtime.
    """
    if validate is not None:
        extra = kwargs.get("json_schema_extra") or {}
        extra["validate"] = validate
        kwargs["json_schema_extra"] = extra
    return _PydanticField(default, alias=alias, **kwargs)


# ---------------------------------------------------------------------------
# Tag parser
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


def _parse_validate_tag(tag: str) -> dict:
    """
    Parse a validation tag string into a rule dictionary.

    Examples:
        "required,type=str"              → {"required": True, "type": str}
        "required,type=int,gt=0"         → {"required": True, "type": int, "gt": 0}
        "oneof=On Off PoweringOn"        → {"oneof": ("On", "Off", "PoweringOn")}
        "status"                         → {"status": True}
        "gte_field=total_cores"          → {"gte_field": "total_cores"}
    """
    rules = {}
    for part in tag.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, val = part.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key == "type":
                rules["type"] = _TYPE_MAP[val]
            elif key in ("gt", "ge", "lt", "le"):
                rules[key] = float(val) if "." in val else int(val)
            elif key == "oneof":
                rules["oneof"] = tuple(val.split())
            elif key.endswith("_field"):
                rules[key] = val  # Cross-field reference; store the field name
            else:
                rules[key] = val
        else:
            # Valueless tags: required, status, list
            rules[part] = True
    return rules


# ---------------------------------------------------------------------------
# Generic validation engine
# ---------------------------------------------------------------------------

def validate_model(obj: BaseModel) -> None:
    """
    Validate a model using the validation tags declared on its fields.

    Behavior:
        - A required None or empty string emits a warning without failing.
        - A type mismatch raises AssertionError.
        - An out-of-range value raises AssertionError.
        - An invalid enumeration value raises AssertionError.

    Usage:
        validate_model(processor_instance)
    """
    resource_id = getattr(obj, "odata_id", "unknown")
    cls_name = obj.__class__.__name__

    for field_name, field_info in obj.__class__.model_fields.items():
        extra = field_info.json_schema_extra
        if not extra or "validate" not in extra:
            continue

        tag = extra["validate"]
        rules = _parse_validate_tag(tag)
        value = getattr(obj, field_name, None)

        # Special handling for status
        if rules.get("status"):
            if value is not None:
                _check_status(value, cls_name, resource_id)
            continue

        required = rules.get("required", False)

        # None check
        if value is None:
            if required:
                warnings.warn(
                    f"{cls_name}.{field_name} is None (resource={resource_id})",
                    stacklevel=2,
                )
            continue

        # Empty-string check
        if isinstance(value, str) and value == "":
            if required:
                warnings.warn(
                    f"{cls_name}.{field_name} is empty (resource={resource_id})",
                    stacklevel=2,
                )
            continue

        # List tag
        if rules.get("list"):
            assert isinstance(value, list), (
                f"{cls_name}.{field_name} has invalid type: expected list, "
                f"got {type(value).__name__} (resource={resource_id})"
            )
            continue

        # Type check
        expected = rules.get("type")
        if expected is not None:
            if expected is float:
                assert isinstance(value, (int, float)), (
                    f"{cls_name}.{field_name} has invalid type: expected number, "
                    f"got {type(value).__name__} (value={value!r}, resource={resource_id})"
                )
            else:
                assert isinstance(value, expected), (
                    f"{cls_name}.{field_name} has invalid type: expected {expected.__name__}, "
                    f"got {type(value).__name__} (value={value!r}, resource={resource_id})"
                )

        # gt / ge / lt / le range checks
        if isinstance(value, (int, float)):
            if "gt" in rules:
                assert value > rules["gt"], (
                    f"{cls_name}.{field_name} should be > {rules['gt']}, "
                    f"got {value} (resource={resource_id})"
                )
            if "ge" in rules:
                assert value >= rules["ge"], (
                    f"{cls_name}.{field_name} should be >= {rules['ge']}, "
                    f"got {value} (resource={resource_id})"
                )
            if "lt" in rules:
                assert value < rules["lt"], (
                    f"{cls_name}.{field_name} should be < {rules['lt']}, "
                    f"got {value} (resource={resource_id})"
                )
            if "le" in rules:
                assert value <= rules["le"], (
                    f"{cls_name}.{field_name} should be <= {rules['le']}, "
                    f"got {value} (resource={resource_id})"
                )

        # oneof enumeration check
        if "oneof" in rules and isinstance(value, str):
            assert value in rules["oneof"], (
                f"{cls_name}.{field_name} is outside the allowed values: "
                f"got {value!r}, allowed={rules['oneof']} (resource={resource_id})"
            )

        # gte_field cross-field check
        if "gte_field" in rules and isinstance(value, (int, float)):
            other_name = rules["gte_field"]
            other_val = getattr(obj, other_name, None)
            if other_val is not None and isinstance(other_val, (int, float)):
                assert value >= other_val, (
                    f"{cls_name}.{field_name} ({value}) should be >= "
                    f"{other_name} ({other_val}) (resource={resource_id})"
                )


def _check_status(status: Any, parent_cls: str, resource_id: str) -> None:
    """Validate a nested Status object."""
    from redfish_sdk.models.common import Status

    assert isinstance(status, Status), (
        f"{parent_cls}.status has invalid type: expected Status, "
        f"got {type(status).__name__} (resource={resource_id})"
    )
    if status.state is not None:
        assert isinstance(status.state, str), (
            f"{parent_cls}.status.state has invalid type: expected str, "
            f"got {type(status.state).__name__} (resource={resource_id})"
        )
    if status.health is not None:
        assert isinstance(status.health, str), (
            f"{parent_cls}.status.health has invalid type: expected str, "
            f"got {type(status.health).__name__} (resource={resource_id})"
        )
