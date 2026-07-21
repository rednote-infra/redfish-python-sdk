"""
模型层注解式校验引擎。

提供自定义 Field() 包装和 validate_model() 通用校验函数，
实现 Go playground/validator 风格的 struct tag 声明式校验。

用法:
    # 模型定义（替换 from pydantic import Field）
    from redfish_sdk.models.check import Field

    class Processor(Entity):
        manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="required,type=str")
        total_cores:  Optional[int] = Field(None, alias="TotalCores",   validate="required,type=int,gt=0")

    # 校验（测试代码中调用）
    from redfish_sdk.models.check import validate_model
    validate_model(processor_instance)
"""
from __future__ import annotations

import warnings
from typing import Any

from pydantic import BaseModel
from pydantic import Field as _PydanticField

# ---------------------------------------------------------------------------
# 自定义 Field() 包装
# ---------------------------------------------------------------------------

def Field(default=None, *, alias=None, validate=None, **kwargs):
    """
    Pydantic Field 的增强包装，新增 validate 参数。

    用法与原生 Field 完全一致，额外支持 validate 标签:
        Field(None, alias="Manufacturer", validate="required,type=str")

    内部实现: 将 validate 字符串存入 json_schema_extra，
    供 validate_model() 在运行时读取。
    """
    if validate is not None:
        extra = kwargs.get("json_schema_extra") or {}
        extra["validate"] = validate
        kwargs["json_schema_extra"] = extra
    return _PydanticField(default, alias=alias, **kwargs)


# ---------------------------------------------------------------------------
# 标签解析器
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


def _parse_validate_tag(tag: str) -> dict:
    """
    解析 validate 标签字符串为规则字典。

    示例:
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
                rules[key] = val  # 跨字段引用，存字段名
            else:
                rules[key] = val
        else:
            # 无值标签：required, status, list
            rules[part] = True
    return rules


# ---------------------------------------------------------------------------
# 通用校验引擎
# ---------------------------------------------------------------------------

def validate_model(obj: BaseModel) -> None:
    """
    根据模型字段上的 validate 标签自动执行校验。

    行为:
        - required 且值为 None/空字符串 → warnings.warn（WARN，不失败）
        - 类型不匹配 → AssertionError（FAIL）
        - 值域不满足 → AssertionError（FAIL）
        - 枚举不匹配 → AssertionError（FAIL）

    用法:
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

        # --- status 特殊处理 ---
        if rules.get("status"):
            if value is not None:
                _check_status(value, cls_name, resource_id)
            continue

        required = rules.get("required", False)

        # --- None 检查 ---
        if value is None:
            if required:
                warnings.warn(
                    f"{cls_name}.{field_name} 为 None (resource={resource_id})",
                    stacklevel=2,
                )
            continue

        # --- 空字符串检查 ---
        if isinstance(value, str) and value == "":
            if required:
                warnings.warn(
                    f"{cls_name}.{field_name} 为空字符串 (resource={resource_id})",
                    stacklevel=2,
                )
            continue

        # --- list 标签 ---
        if rules.get("list"):
            assert isinstance(value, list), (
                f"{cls_name}.{field_name} 类型错误: 期望 list, "
                f"实际 {type(value).__name__} (resource={resource_id})"
            )
            continue

        # --- type 类型检查 ---
        expected = rules.get("type")
        if expected is not None:
            if expected is float:
                assert isinstance(value, (int, float)), (
                    f"{cls_name}.{field_name} 类型错误: 期望 数字, "
                    f"实际 {type(value).__name__} (值={value!r}, resource={resource_id})"
                )
            else:
                assert isinstance(value, expected), (
                    f"{cls_name}.{field_name} 类型错误: 期望 {expected.__name__}, "
                    f"实际 {type(value).__name__} (值={value!r}, resource={resource_id})"
                )

        # --- gt / ge / lt / le 值域检查 ---
        if isinstance(value, (int, float)):
            if "gt" in rules:
                assert value > rules["gt"], (
                    f"{cls_name}.{field_name} 应 > {rules['gt']}, "
                    f"实际={value} (resource={resource_id})"
                )
            if "ge" in rules:
                assert value >= rules["ge"], (
                    f"{cls_name}.{field_name} 应 >= {rules['ge']}, "
                    f"实际={value} (resource={resource_id})"
                )
            if "lt" in rules:
                assert value < rules["lt"], (
                    f"{cls_name}.{field_name} 应 < {rules['lt']}, "
                    f"实际={value} (resource={resource_id})"
                )
            if "le" in rules:
                assert value <= rules["le"], (
                    f"{cls_name}.{field_name} 应 <= {rules['le']}, "
                    f"实际={value} (resource={resource_id})"
                )

        # --- oneof 枚举检查 ---
        if "oneof" in rules and isinstance(value, str):
            assert value in rules["oneof"], (
                f"{cls_name}.{field_name} 值不在允许范围: "
                f"实际={value!r}, 允许={rules['oneof']} (resource={resource_id})"
            )

        # --- gte_field 跨字段检查 ---
        if "gte_field" in rules and isinstance(value, (int, float)):
            other_name = rules["gte_field"]
            other_val = getattr(obj, other_name, None)
            if other_val is not None and isinstance(other_val, (int, float)):
                assert value >= other_val, (
                    f"{cls_name}.{field_name} ({value}) 应 >= "
                    f"{other_name} ({other_val}) (resource={resource_id})"
                )


def _check_status(status: Any, parent_cls: str, resource_id: str) -> None:
    """校验 Status 子对象。"""
    from redfish_sdk.models.common import Status

    assert isinstance(status, Status), (
        f"{parent_cls}.status 类型错误: 期望 Status, "
        f"实际 {type(status).__name__} (resource={resource_id})"
    )
    if status.state is not None:
        assert isinstance(status.state, str), (
            f"{parent_cls}.status.state 类型错误: "
            f"期望 str, 实际 {type(status.state).__name__} (resource={resource_id})"
        )
    if status.health is not None:
        assert isinstance(status.health, str), (
            f"{parent_cls}.status.health 类型错误: "
            f"期望 str, 实际 {type(status.health).__name__} (resource={resource_id})"
        )
