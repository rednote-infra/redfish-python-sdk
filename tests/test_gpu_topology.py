"""Offline coverage for standards-based GPU topology discovery."""

import json
from pathlib import Path

import pytest

from redfish_sdk import RedfishClient
from redfish_sdk.managers.chassis import ChassisManager
from redfish_sdk.models.chassis import Chassis
from redfish_sdk.models.systems import System


@pytest.fixture(scope="module")
def topology_cases():
    fixture_path = Path(__file__).parents[1] / "testdata" / "gpu_topology.json"
    return json.loads(fixture_path.read_text())


def discover(monkeypatch, case):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    system = System.model_validate(case["system"])
    monkeypatch.setattr(client, "_get_systems_collection", lambda: [system])
    monkeypatch.setattr(
        ChassisManager,
        "get",
        lambda self: Chassis.model_construct(odata_id="/topology/chassis"),
    )

    def get_collection(path, model_class):
        return [
            model_class.model_validate(payload)
            for payload in case["collections"].get(path, [])
        ]

    def get_resource(path, model_class):
        return model_class.model_validate(case["resources"][path])

    monkeypatch.setattr(client, "_get_collection", get_collection)
    monkeypatch.setattr(client._http_client, "get", get_resource)
    result = client.get_gpus()
    client.close()
    return result


def test_graphics_controllers_remain_supported(monkeypatch, topology_cases):
    gpus = discover(monkeypatch, topology_cases["graphics_controllers_only"])

    assert [gpu.id for gpu in gpus] == ["graphics-0"]
    assert gpus[0].source_types == ["GraphicsController"]


def test_processor_accelerator_accepts_missing_optional_identity_fields(
    monkeypatch, topology_cases
):
    gpus = discover(monkeypatch, topology_cases["processor_accelerator"])

    assert len(gpus) == 1
    assert gpus[0].manufacturer is None
    assert gpus[0].model is None
    assert gpus[0].version == "2.0"
    assert gpus[0].power_watts == "300"
    assert "/topology/acceleration-functions/video-0" in (
        gpus[0].related_resource_odata_ids
    )


def test_pcie_function_device_class_discovers_gpu_without_gpu_name(
    monkeypatch, topology_cases
):
    gpus = discover(monkeypatch, topology_cases["pcie_only"])

    assert [gpu.id for gpu in gpus] == ["device-0"]
    assert gpus[0].version == "3.0"
    assert gpus[0].power_watts is None


def test_mixed_topology_merges_related_representations_deterministically(
    monkeypatch, topology_cases
):
    gpus = discover(monkeypatch, topology_cases["mixed_duplicate"])

    assert len(gpus) == 1
    assert gpus[0].id == "graphics-0"
    assert gpus[0].model == "G250"
    assert gpus[0].source_types == ["GraphicsController", "PCIeDevice"]
    assert gpus[0].source_odata_ids == [
        "/topology/graphics/0",
        "/topology/pcie-devices/0",
    ]


def test_non_gpu_pcie_topology_is_not_manufactured(monkeypatch, topology_cases):
    assert discover(monkeypatch, topology_cases["no_gpu"]) == []


def test_gpu_discovery_combines_multiple_advertised_systems(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    systems = [
        System.model_validate(
            {
                "@odata.id": "/redfish/v1/Systems/Baseboard",
                "Id": "Baseboard",
            }
        ),
        System.model_validate(
            {
                "@odata.id": "/redfish/v1/Systems/Compute",
                "Id": "Compute",
                "Processors": {"@odata.id": "/topology/compute/processors"},
            }
        ),
    ]
    monkeypatch.setattr(client, "_get_systems_collection", lambda: systems)
    monkeypatch.setattr(
        ChassisManager,
        "get",
        lambda self: Chassis.model_construct(odata_id="/topology/chassis"),
    )

    def get_collection(path, model_class):
        if path == "/topology/compute/processors":
            return [
                model_class.model_validate(
                    {
                        "@odata.id": "/topology/compute/processors/gpu-0",
                        "Id": "gpu-0",
                        "ProcessorType": "GPU",
                        "Manufacturer": "Example",
                        "Model": "Accelerator",
                    }
                )
            ]
        return []

    monkeypatch.setattr(client, "_get_collection", get_collection)

    gpus = client.get_gpus()

    assert [gpu.id for gpu in gpus] == ["gpu-0"]
    client.close()
