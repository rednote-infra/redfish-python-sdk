"""Offline JSON loading and model-deserialization helpers.

Loads files collected by tools/redfish_drill.py into Pydantic models for
test_offline_json.py. File naming follows redfish_drill.py; for example,
@odata.id "/redfish/v1/Systems/1" maps to "redfish_v1_Systems_1.json".
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
    Load Redfish resources from JSON files collected by redfish_drill.py.

    Supports loading individual resources by @odata.id, expanding collection
    members, finding resources by path pattern, and reading raw JSON.
    """

    def __init__(self, json_dir: str):
        """
        Args:
            json_dir: Directory containing JSON files.
        """
        self.json_dir = json_dir
        self._file_cache: Dict[str, dict] = {}  # odata_id -> json_data
        self._scan_files()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _odata_id_to_filename(odata_id: str) -> str:
        """Convert an @odata.id to the filename used by redfish_drill.py."""
        name = odata_id.replace("/", "_")
        if name.startswith("_"):
            name = name[1:]
        return f"{name}.json"

    def _scan_files(self) -> None:
        """Scan JSON files and build an odata_id-to-data index."""
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
        """Load directly by filename when the cache has no matching entry."""
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
        Return the raw JSON dictionary for an @odata.id.

        Returns:
            Raw JSON dictionary, or None when the file is absent.
        """
        data = self._file_cache.get(odata_id)
        if data is None:
            data = self._load_file_by_name(odata_id)
        return data

    def load(self, odata_id: str, model_class: Type[T]) -> Optional[T]:
        """
        Load JSON for an @odata.id and deserialize it as a Pydantic model.

        Args:
            odata_id: Redfish resource path such as "/redfish/v1/Systems/1".
            model_class: Pydantic model class.

        Returns:
            Deserialized model, or None when the file is absent.
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
        Load every member of a collection resource.

        The collection JSON supplies member @odata.id values, and each member
        is loaded from its individual JSON file.

        Args:
            collection_odata_id: Collection resource @odata.id.
            member_model_class: Pydantic model class for each member.

        Returns:
            Deserialized member models.
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
        Find @odata.id values containing a path keyword.

        Args:
            pattern: Path keyword such as "Processors" or "Memory".

        Returns:
            Matching @odata.id values.
        """
        return [oid for oid in self._file_cache if pattern in oid]

    def find_system_id(self) -> Optional[str]:
        """
        Discover the System resource @odata.id, preferring
        /redfish/v1/Systems/1 and otherwise using the first direct child.
        """
        default = "/redfish/v1/Systems/1"
        if default in self._file_cache:
            return default
        for oid in self._file_cache:
            # Match /redfish/v1/Systems/{id}, excluding deeper resources
            if "/Systems/" in oid and oid.count("/") == 4:
                return oid
        return None

    def find_chassis_id(self) -> Optional[str]:
        """Discover the Chassis resource @odata.id."""
        default = "/redfish/v1/Chassis/1"
        if default in self._file_cache:
            return default
        for oid in self._file_cache:
            if "/Chassis/" in oid and oid.count("/") == 4:
                return oid
        return None

    @property
    def server_label(self) -> str:
        """Return the data-directory name as the server label."""
        return os.path.basename(self.json_dir.rstrip("/"))

    @property
    def available_odata_ids(self) -> List[str]:
        """Return all cached @odata.id values."""
        return list(self._file_cache.keys())


# ---------------------------------------------------------------------------
# Directory discovery
# ---------------------------------------------------------------------------

def discover_json_dirs(base_dir: str) -> List[str]:
    """
    Discover JSON data directories.

    Supports a single directory containing JSON files or a parent directory
    whose child directories each represent one server.

    Args:
        base_dir: Root directory path.

    Returns:
        Directory paths containing JSON files.
    """
    if not os.path.isdir(base_dir):
        return []

    # Check for JSON files directly under base_dir (single-directory mode)
    entries = os.listdir(base_dir)
    if any(f.endswith(".json") for f in entries if os.path.isfile(os.path.join(base_dir, f))):
        return [base_dir]

    # Multi-directory mode: scan child directories
    dirs: List[str] = []
    for entry in sorted(entries):
        subdir = os.path.join(base_dir, entry)
        if os.path.isdir(subdir):
            sub_entries = os.listdir(subdir)
            if any(f.endswith(".json") for f in sub_entries):
                dirs.append(subdir)
    return dirs
