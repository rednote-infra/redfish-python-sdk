#!/usr/bin/env python3
"""Refresh, verify, and report the pinned DMTF compatibility baseline."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

DMTF_RELEASE = "2026.2"
DMTF_COMMIT = "4f81814e399213c9055863ddaff42791c6b3706a"
RAW_BASE = f"https://raw.githubusercontent.com/DMTF/Redfish-Publications/{DMTF_COMMIT}"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/fixtures/dmtf/2026.2/manifest.json"
DEFAULT_REPORT = ROOT / "compatibility/dmtf-2026.2-coverage.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESOURCE_MODELS = {
    "ServiceRoot": "redfish_sdk.models.root:RootService",
    "ComputerSystem": "redfish_sdk.models.systems:System",
    "Chassis": "redfish_sdk.models.chassis:Chassis",
    "Manager": "redfish_sdk.models.managers:Manager",
    "Task": "redfish_sdk.models.task:Task",
    "MessageRegistryFile": "redfish_sdk.models.registry:Registry",
    "UpdateService": "redfish_sdk.models.update:UpdateService",
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "redfish-python-sdk-compatibility"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _fetch_json(url: str) -> dict[str, Any]:
    return json.loads(_fetch_bytes(url))


def _load_model(reference: str) -> type[Any]:
    module_name, class_name = reference.split(":", 1)
    return getattr(importlib.import_module(module_name), class_name)


def _model_aliases(reference: str) -> list[str]:
    model = _load_model(reference)
    aliases: set[str] = set()
    for name, field in model.model_fields.items():
        aliases.add(field.alias or name)
        validation_alias = field.validation_alias
        if isinstance(validation_alias, str):
            aliases.add(validation_alias)
        else:
            for choice in getattr(validation_alias, "choices", ()):
                if isinstance(choice, str):
                    aliases.add(choice)
    return sorted(aliases)


def _latest_versioned_schema(resource: str) -> tuple[str, dict[str, Any]]:
    index = _fetch_json(f"{RAW_BASE}/json-schema/{resource}.json")
    references = index["definitions"][resource]["anyOf"]
    candidates: list[tuple[tuple[int, ...], str]] = []
    for item in references:
        reference = item.get("$ref", "")
        match = re.search(rf"/({re.escape(resource)}\.v(\d+_\d+_\d+)\.json)#", reference)
        if match:
            version = tuple(int(part) for part in match.group(2).split("_"))
            candidates.append((version, match.group(1)))
    if not candidates:
        raise ValueError(f"No versioned schema reference found for {resource}")
    _, filename = max(candidates)
    return filename, _fetch_json(f"{RAW_BASE}/json-schema/{filename}")


def build_report() -> dict[str, Any]:
    resources: dict[str, Any] = {}
    for resource, model_reference in RESOURCE_MODELS.items():
        schema_file, schema = _latest_versioned_schema(resource)
        properties = sorted(schema["definitions"][resource].get("properties", {}))
        aliases = _model_aliases(model_reference)
        resources[resource] = {
            "model": model_reference,
            "schema_file": schema_file,
            "schema_properties": properties,
            "sdk_fields": aliases,
        }
    return {
        "dmtf_release": DMTF_RELEASE,
        "dmtf_commit": DMTF_COMMIT,
        "scope": "Top-level properties only; nested definitions require separate review.",
        "resources": resources,
    }


def render_report(baseline: dict[str, Any]) -> dict[str, Any]:
    """Derive review classifications from the committed minimal baseline."""
    report = dict(baseline)
    report["resources"] = {}
    for resource, recorded in baseline["resources"].items():
        schema_properties = set(recorded["schema_properties"])
        sdk_fields = set(recorded["sdk_fields"])
        report["resources"][resource] = {
            **recorded,
            "typed_schema_properties": sorted(schema_properties & sdk_fields),
            "untyped_schema_properties": sorted(schema_properties - sdk_fields),
            "sdk_only_aliases": sorted(sdk_fields - schema_properties),
        }
    return report


def refresh_fixtures(manifest_path: Path) -> None:
    manifest = _read_json(manifest_path)
    if manifest["release"] != DMTF_RELEASE or manifest["commit"] != DMTF_COMMIT:
        raise ValueError("Fixture manifest does not match the pinned DMTF baseline")
    destination = manifest_path.parent
    for fixture in manifest["fixtures"]:
        content = _fetch_bytes(f"{RAW_BASE}/{fixture['source']}")
        digest = hashlib.sha256(content).hexdigest()
        if digest != fixture["sha256"]:
            raise ValueError(f"Checksum mismatch for {fixture['source']}: {digest}")
        (destination / fixture["file"]).write_bytes(content)


def check(report_path: Path, manifest_path: Path) -> None:
    report = _read_json(report_path)
    manifest = _read_json(manifest_path)
    for payload, label in ((report, "coverage report"), (manifest, "fixture manifest")):
        release_key = "dmtf_release" if label == "coverage report" else "release"
        commit_key = "dmtf_commit" if label == "coverage report" else "commit"
        if payload[release_key] != DMTF_RELEASE or payload[commit_key] != DMTF_COMMIT:
            raise ValueError(f"{label} does not match the pinned DMTF baseline")

    for resource, model_reference in RESOURCE_MODELS.items():
        recorded = report["resources"][resource]
        if recorded["model"] != model_reference:
            raise ValueError(f"Model mapping changed for {resource}; refresh the coverage report")
        current_aliases = _model_aliases(model_reference)
        if recorded["sdk_fields"] != current_aliases:
            raise ValueError(
                f"SDK fields changed for {resource}; refresh and review the coverage report"
            )
        if recorded["schema_properties"] != sorted(set(recorded["schema_properties"])):
            raise ValueError(f"Schema properties are not sorted and unique for {resource}")

    fixture_dir = manifest_path.parent
    for fixture in manifest["fixtures"]:
        fixture_path = fixture_dir / fixture["file"]
        if not fixture_path.is_file():
            raise ValueError(f"Missing fixture: {fixture_path}")
        digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        if digest != fixture["sha256"]:
            raise ValueError(f"Fixture checksum mismatch: {fixture_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser("refresh-report", help="Fetch pinned schemas and regenerate the report")
    refresh_parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)

    fixtures_parser = subparsers.add_parser("refresh-fixtures", help="Download and verify pinned public fixtures")
    fixtures_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)

    check_parser = subparsers.add_parser("check", help="Verify committed fixtures and coverage without network access")
    check_parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    check_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)

    report_parser = subparsers.add_parser(
        "report", help="Print the derived coverage report without network access"
    )
    report_parser.add_argument("--baseline", type=Path, default=DEFAULT_REPORT)

    arguments = parser.parse_args()
    try:
        if arguments.command == "refresh-report":
            _write_json(arguments.output, build_report())
        elif arguments.command == "refresh-fixtures":
            refresh_fixtures(arguments.manifest)
        elif arguments.command == "check":
            check(arguments.report, arguments.manifest)
        else:
            print(
                json.dumps(
                    render_report(_read_json(arguments.baseline)),
                    indent=2,
                    sort_keys=True,
                )
            )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"compatibility check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
