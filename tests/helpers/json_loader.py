"""
离线 JSON 文件加载与模型反序列化工具。

将 tools/redfish_drill.py 采集的 JSON 文件加载为 Pydantic 模型对象，
供 test_offline_json.py 中的测试用例使用。

文件命名规则（与 redfish_drill.py 一致）:
  @odata.id "/redfish/v1/Systems/1" → 文件名 "redfish_v1_Systems_1.json"
"""
from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class RedfishJsonLoader:
    """
    从 redfish_drill.py 采集的 JSON 文件中加载 Redfish 资源。

    支持:
    - 按 @odata.id 加载单个资源
    - 加载集合资源的所有成员
    - 按路径模式查找资源
    - 获取原始 JSON 数据（用于 key-present-but-empty 校验）
    """

    def __init__(self, json_dir: str):
        """
        Args:
            json_dir: JSON 文件所在目录路径
        """
        self.json_dir = json_dir
        self._file_cache: Dict[str, dict] = {}  # odata_id -> json_data
        self._scan_files()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _odata_id_to_filename(odata_id: str) -> str:
        """将 @odata.id 转为文件名（与 redfish_drill.py 一致）。"""
        name = odata_id.replace("/", "_")
        if name.startswith("_"):
            name = name[1:]
        return f"{name}.json"

    def _scan_files(self) -> None:
        """扫描目录下所有 JSON 文件，建立 odata_id -> json_data 索引。"""
        for filepath in glob.glob(os.path.join(self.json_dir, "*.json")):
            filename = os.path.basename(filepath)
            if filename == "all_odata_id.json":
                continue
            try:
                with open(filepath, encoding="utf-8") as f:
                    data = json.load(f)
                odata_id = data.get("@odata.id", "")
                if odata_id:
                    self._file_cache[odata_id] = data
            except (json.JSONDecodeError, OSError):
                pass

    def _load_file_by_name(self, odata_id: str) -> Optional[dict]:
        """尝试通过文件名直接加载（缓存未命中时的后备方案）。"""
        filename = self._odata_id_to_filename(odata_id)
        filepath = os.path.join(self.json_dir, filename)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            self._file_cache[odata_id] = data
            return data
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_raw(self, odata_id: str) -> Optional[dict]:
        """
        获取指定 @odata.id 的原始 JSON 字典。

        Returns:
            原始 JSON 字典, 文件不存在则返回 None
        """
        data = self._file_cache.get(odata_id)
        if data is None:
            data = self._load_file_by_name(odata_id)
        return data

    def load(self, odata_id: str, model_class: Type[T]) -> Optional[T]:
        """
        加载指定 @odata.id 对应的 JSON 并反序列化为 Pydantic 模型。

        Args:
            odata_id: Redfish 资源路径，如 "/redfish/v1/Systems/1"
            model_class: Pydantic 模型类

        Returns:
            反序列化后的模型对象，文件不存在则返回 None
        """
        data = self.get_raw(odata_id)
        if data is None:
            return None
        return model_class.model_validate(data)

    def load_collection_members(
        self,
        collection_odata_id: str,
        member_model_class: Type[T],
    ) -> List[T]:
        """
        加载集合资源的所有成员。

        1. 先加载集合 JSON，从 Members 列表提取各成员的 @odata.id
        2. 逐个加载成员的独立 JSON 文件并反序列化

        Args:
            collection_odata_id: 集合资源的 @odata.id
            member_model_class: 成员的 Pydantic 模型类

        Returns:
            反序列化后的成员模型列表
        """
        collection_data = self.get_raw(collection_odata_id)
        if collection_data is None:
            return []

        members: List[T] = []
        for member_link in collection_data.get("Members", []):
            member_odata_id = member_link.get("@odata.id", "")
            if not member_odata_id:
                continue
            member = self.load(member_odata_id, member_model_class)
            if member is not None:
                members.append(member)
        return members

    def find_by_path_pattern(self, pattern: str) -> List[str]:
        """
        根据路径关键词查找匹配的 @odata.id。

        Args:
            pattern: 路径中的关键词，如 "Processors"、"Memory"

        Returns:
            匹配的 @odata.id 列表
        """
        return [oid for oid in self._file_cache if pattern in oid]

    def find_system_id(self) -> Optional[str]:
        """
        自动发现 System 资源的 @odata.id。
        优先匹配 /redfish/v1/Systems/1，否则匹配第一个 Systems/ 子资源。
        """
        default = "/redfish/v1/Systems/1"
        if default in self._file_cache:
            return default
        for oid in self._file_cache:
            # 匹配 /redfish/v1/Systems/{id} 但排除更深层级
            if "/Systems/" in oid and oid.count("/") == 4:
                return oid
        return None

    def find_chassis_id(self) -> Optional[str]:
        """自动发现 Chassis 资源的 @odata.id。"""
        default = "/redfish/v1/Chassis/1"
        if default in self._file_cache:
            return default
        for oid in self._file_cache:
            if "/Chassis/" in oid and oid.count("/") == 4:
                return oid
        return None

    @property
    def server_label(self) -> str:
        """返回数据目录名作为服务器标识。"""
        return os.path.basename(self.json_dir.rstrip("/"))

    @property
    def available_odata_ids(self) -> List[str]:
        """返回所有已缓存的 @odata.id 列表。"""
        return list(self._file_cache.keys())


# ---------------------------------------------------------------------------
# 目录发现
# ---------------------------------------------------------------------------

def discover_json_dirs(base_dir: str) -> List[str]:
    """
    发现 JSON 数据目录。

    支持两种目录结构:
    1. 单目录: base_dir 下直接包含 .json 文件
    2. 多目录: base_dir 下有多个子目录，每个子目录对应一台服务器

    Args:
        base_dir: 根目录路径

    Returns:
        包含 JSON 文件的目录路径列表
    """
    if not os.path.isdir(base_dir):
        return []

    # 检查 base_dir 下是否直接有 JSON 文件（单目录模式）
    entries = os.listdir(base_dir)
    if any(f.endswith(".json") for f in entries if os.path.isfile(os.path.join(base_dir, f))):
        return [base_dir]

    # 多目录模式：扫描子目录
    dirs: List[str] = []
    for entry in sorted(entries):
        subdir = os.path.join(base_dir, entry)
        if os.path.isdir(subdir):
            sub_entries = os.listdir(subdir)
            if any(f.endswith(".json") for f in sub_entries):
                dirs.append(subdir)
    return dirs
