"""Deterministic compatibility checks against pinned public DMTF fixtures."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from redfish_sdk.models.chassis import Chassis
from redfish_sdk.models.registry import Registry
from redfish_sdk.models.task import Task
from redfish_sdk.models.update import UpdateService

FIXTURE_DIR = Path(__file__).parent / "fixtures/dmtf/2026.2"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))


def _load_model(reference: str) -> type[Any]:
    module_name, class_name = reference.split(":", 1)
    return getattr(importlib.import_module(module_name), class_name)


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda item: item["file"])
def test_pinned_dmtf_fixture_checksum_and_model_compatibility(fixture):
    fixture_path = FIXTURE_DIR / fixture["file"]
    content = fixture_path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == fixture["sha256"]

    payload = json.loads(content)
    model = _load_model(fixture["model"])
    resource = model.model_validate(payload)

    assert resource.odata_id == payload["@odata.id"]
    assert str(resource.id) == str(payload["Id"])


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda item: item["file"])
def test_unknown_fields_and_missing_optional_links_remain_compatible(fixture):
    payload = json.loads((FIXTURE_DIR / fixture["file"]).read_text(encoding="utf-8"))
    payload = copy.deepcopy(payload)
    payload["FutureOptionalProperty"] = {"Value": 1}
    for optional_link in ("Systems", "Chassis", "Managers", "Links", "Actions"):
        payload.pop(optional_link, None)

    resource = _load_model(fixture["model"]).model_validate(payload)

    assert resource.model_extra["FutureOptionalProperty"] == {"Value": 1}


def test_referenced_registry_uses_standard_registry_property():
    payload = json.loads(
        (FIXTURE_DIR / "MessageRegistryFile-v1-example.json").read_text(encoding="utf-8")
    )

    registry = Registry.model_validate(payload)

    assert registry.registry_prefix == "Base.1.0"
    assert registry.location[0].archive_file == "Base.1.0.0.json"


def test_task_suspension_and_legacy_single_message_are_tolerated():
    task = Task.model_validate(
        {
            "Id": "legacy-task",
            "TaskState": "Suspended",
            "Messages": {
                "MessageId": "Base.1.0.ServiceTemporarilyUnavailable",
                "Message": "Retry later",
            },
        }
    )

    assert task.task_state == "Suspended"
    assert task.messages[0].message_id == "Base.1.0.ServiceTemporarilyUnavailable"


def test_deprecated_indicator_led_remains_compatible():
    chassis = Chassis.model_validate(
        {
            "Id": "legacy-chassis",
            "IndicatorLED": "Lit",
            "LocationIndicatorActive": True,
        }
    )

    assert chassis.indicator_led == "Lit"
    assert chassis.model_extra["LocationIndicatorActive"] is True


def test_multipart_uri_accepts_standard_and_legacy_spelling():
    standard = UpdateService.model_validate({"MultipartHttpPushUri": "/standard"})
    legacy = UpdateService.model_validate({"MultiPartHttpPushUri": "/legacy"})

    assert standard.multi_part_http_push_uri == "/standard"
    assert legacy.multi_part_http_push_uri == "/legacy"
