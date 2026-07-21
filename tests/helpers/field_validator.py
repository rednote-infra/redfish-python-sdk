"""
通用字段校验工具函数。

注意: 原有的 validate_system()、validate_processor() 等组合校验函数已迁移到
模型层的 validate 标签 + redfish_sdk.models.check.validate_model() 引擎。
本文件仅保留 validate_json_key_present_but_empty()，用于离线模式下的原始 JSON 检查。
"""
from __future__ import annotations

import warnings

# ---------------------------------------------------------------------------
# 原始 JSON 校验（标签非空但实际为空检查）
# ---------------------------------------------------------------------------

def validate_json_key_present_but_empty(
    json_data: dict,
    model_class_name: str,
    odata_id: str = "",
) -> None:
    """
    检查 JSON 原始数据中 key 存在但 value 为 null 或空字符串的情况。
    （「属性的 value 标签若不为空，实际返回若为空，需要提示」）

    Args:
        json_data: 原始 JSON 字典
        model_class_name: 模型类名（用于告警信息）
        odata_id: 资源 ID（用于告警信息）
    """
    for key, value in json_data.items():
        if key.startswith("@"):
            continue  # 跳过 @odata.xxx 元数据字段
        if value is None or (isinstance(value, str) and value.strip() == ""):
            warnings.warn(
                f"{model_class_name}.{key} 在数据中存在但值为空 "
                f"(resource={odata_id})",
                stacklevel=2,
            )
