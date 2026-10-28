"""CXL and UALink coverage using DMTF 2026.2 and sparse topology payloads."""

from __future__ import annotations

import pytest

from redfish_sdk import CXLLogicalDevice, Port, PortMetrics, RedfishClient
from redfish_sdk.exceptions import RedfishNotFoundError, RedfishValidationError
from redfish_sdk.models.fabric import Port as PortModel
from redfish_sdk.models.pcie_device import PCIeDevice
from redfish_sdk.models.processor import Processor

DMTF_PUBLICATIONS_COMMIT = "4f81814e399213c9055863ddaff42791c6b3706a"
# Copied from mockups/DSP2046-examples/*-v1-example.json at the pinned commit.
DMTF_EXAMPLES = {
    "Processor": {
        "@odata.type": "#Processor.v1_24_0.Processor",
        "Name": "Processor",
        "Id": "1",
        "Socket": "CPU 1",
        "ProcessorType": "CPU",
        "ProcessorArchitecture": "x86",
        "InstructionSet": "x86-64",
        "Manufacturer": "Intel(R) Corporation",
        "Model": "Multi-Core Intel(R) Xeon(R) processor 7xxx Series",
        "ProcessorId": {
            "VendorId": "GenuineIntel",
            "IdentificationRegisters": "0x34AC34DC8901274A",
            "EffectiveFamily": "0x42",
            "EffectiveModel": "0x61",
            "Step": "0x1",
            "MicrocodeInfo": "0x429943",
        },
        "MaxSpeedMHz": 3700,
        "TotalCores": 8,
        "TotalThreads": 16,
        "Status": {"State": "Enabled", "Health": "OK"},
        "Location": {
            "PartLocation": {
                "ServiceLabel": "Processor 1",
                "LocationType": "Socket",
                "LocationOrdinalValue": 0,
            }
        },
        "@odata.id": "/redfish/v1/Systems/437XR1138R2/Processors/1",
    },
    "Port": {
        "@odata.type": "#Port.v1_20_0.Port",
        "Id": "1",
        "Name": "SAS Port 1",
        "Description": "SAS Port 1",
        "Status": {"State": "Enabled", "Health": "OK"},
        "PortId": "1",
        "PortProtocol": "SAS",
        "PortType": "BidirectionalPort",
        "CurrentSpeedGbps": 48,
        "Width": 4,
        "ConfiguredSpeedGbps": 48,
        "ConfiguredWidth": 4,
        "MaxSpeedGbps": 48,
        "Links": {
            "AssociatedEndpoints": [
                {"@odata.id": "/redfish/v1/Fabrics/SAS/Endpoints/Initiator1"}
            ]
        },
        "@odata.id": "/redfish/v1/Fabrics/SAS/Switches/Switch1/Ports/1",
    },
    "PCIeDevice": {
        "@odata.type": "#PCIeDevice.v1_23_0.PCIeDevice",
        "Id": "NIC",
        "Name": "Simple Two-Port NIC",
        "Description": "Simple Two-Port NIC PCIe Device",
        "AssetTag": "ORD-4302015-18432RS",
        "Manufacturer": "Contoso",
        "Model": "2PNIC 2000",
        "SKU": "89587433",
        "SerialNumber": "2M220100SL",
        "PartNumber": "232-4598D7",
        "DeviceType": "MultiFunction",
        "FirmwareVersion": "12.342-343",
        "Status": {"State": "Enabled", "Health": "OK", "HealthRollup": "OK"},
        "PCIeInterface": {
            "PCIeType": "Gen2",
            "MaxPCIeType": "Gen3",
            "LanesInUse": 4,
            "MaxLanes": 4,
        },
        "PCIeFunctions": {
            "@odata.id": "/redfish/v1/Systems/1/PCIeDevices/NIC/PCIeFunctions"
        },
        "Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
        "@odata.id": "/redfish/v1/Systems/1/PCIeDevices/NIC",
    },
    "CXLLogicalDevice": {
        "@odata.type": "#CXLLogicalDevice.v1_5_0.CXLLogicalDevice",
        "Id": "1",
        "Name": "CXL Logical Device Type 1",
        "Description": "Locally attached CXL Logical Device Type 1",
        "Status": {"State": "Enabled", "Health": "OK", "HealthRollup": "OK"},
        "Identifiers": [
            {
                "DurableName": "4C-1D-96-FF-FE-DD-D8-35:0001",
                "DurableNameFormat": "GCXLID",
            }
        ],
        "SemanticsSupported": ["CXLio", "CXLcache"],
        "Links": {
            "PCIeFunctions": [
                {
                    "@odata.id": "/redfish/v1/Chassis/CXL1/PCIeDevices/1/PCIeFunctions/1"
                }
            ]
        },
        "@odata.id": "/redfish/v1/Chassis/CXL1/PCIeDevices/1/CXLLogicalDevices/1",
    },
}


def test_pinned_dmtf_2026_2_examples_parse_without_optional_fabric_data():
    """Payloads are from Redfish-Publications at DMTF_PUBLICATIONS_COMMIT."""
    assert len(DMTF_PUBLICATIONS_COMMIT) == 40

    processor = Processor.model_validate(DMTF_EXAMPLES["Processor"])
    port = Port.model_validate(DMTF_EXAMPLES["Port"])
    device = PCIeDevice.model_validate(DMTF_EXAMPLES["PCIeDevice"])
    logical_device = CXLLogicalDevice.model_validate(DMTF_EXAMPLES["CXLLogicalDevice"])

    assert processor.odata_type == "#Processor.v1_24_0.Processor"
    assert processor.ualink is None and processor.ports is None
    assert port.odata_type == "#Port.v1_20_0.Port"
    assert port.cxl is None and port.ualink is None
    assert device.odata_type == "#PCIeDevice.v1_23_0.PCIeDevice"
    assert device.device_type == "MultiFunction"
    assert device.cxl_device is None and device.cxl_logical_devices is None
    assert logical_device.odata_type == "#CXLLogicalDevice.v1_5_0.CXLLogicalDevice"
    assert logical_device.semantics_supported == ["CXLio", "CXLcache"]


def test_models_keep_unknown_enums_sparse_fields_and_dynamic_capacity_raw():
    port = Port.model_validate(
        {
            "Id": "future-port",
            "PortProtocol": "FutureFabricProtocol",
            "LinkState": "TrainingWithFutureState",
            "CXL": {
                "ConnectedDeviceMode": "FutureCXLMode",
                "SupportedCXLModes": ["CXL68", "FutureCXLMode"],
            },
            "UALink": {
                "Generation": "UALink9.0",
                "DLState": "FutureDLState",
                "LinkFoldingSupported": True,
            },
            "FuturePortProperty": {"Enabled": True},
        }
    )
    device = PCIeDevice.model_validate(
        {
            "Id": "cxl-device",
            "CXLDevice": {
                "DeviceType": "FutureCXLType",
                "CurrentProtocolVersion": "CXL9.0",
                "DynamicCapacity": {"SanitizationOnReleaseSupport": True},
            },
        }
    )
    logical_device = CXLLogicalDevice.model_validate(
        {"Id": "ld0", "SemanticsSupported": ["FutureSemantic"]}
    )

    assert port.port_protocol == "FutureFabricProtocol"
    assert port.cxl.connected_device_mode == "FutureCXLMode"
    assert port.ualink.dl_state == "FutureDLState"
    assert port.model_extra["FuturePortProperty"] == {"Enabled": True}
    assert device.cxl_device.device_type == "FutureCXLType"
    assert device.cxl_device.model_extra["DynamicCapacity"] == {
        "SanitizationOnReleaseSupport": True
    }
    assert logical_device.semantics_supported == ["FutureSemantic"]


@pytest.fixture
def fabric_client(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    processor = Processor.model_validate(
        {
            "Id": "CPU-A",
            "@odata.id": "/custom/processors/a",
            "Ports": {"@odata.id": "/custom/processor-port-index"},
            "UALink": {"AcceleratorID": 7, "MaxSupportedAcceleratorID": 255},
        }
    )
    processor_port = Port.model_validate(
        {
            "Id": "UP0",
            "@odata.id": "/custom/ports/up0",
            "Metrics": {"@odata.id": "/custom/metrics/up0"},
            "CXL": {"CurrentPortConfigurationState": "Enabled"},
            "Links": {
                "CXLLogicalDevices": [{"@odata.id": "/custom/logical/ld0"}]
            },
        }
    )
    pcie_port = Port.model_validate(
        {"Id": "CP0", "@odata.id": "/custom/ports/cp0", "PortProtocol": "CXL"}
    )
    pcie_device = PCIeDevice.model_validate(
        {
            "Id": "CXL-A",
            "@odata.id": "/custom/pcie/cxl-a",
            "CXLDevice": {"DeviceType": "Type3", "MaxNumberLogicalDevices": 1},
            "CXLLogicalDevices": {"@odata.id": "/custom/logical-index"},
            "Links": {
                "ConnectedPCIePorts": [{"@odata.id": "/custom/ports/cp0"}]
            },
        }
    )
    logical_device = CXLLogicalDevice.model_validate(
        {
            "Id": "LD0",
            "@odata.id": "/custom/logical/ld0",
            "MemorySizeMiB": 4096,
            "SemanticsSupported": ["CXLmem"],
        }
    )
    metrics = PortMetrics.model_validate(
        {
            "Id": "UP0Metrics",
            "@odata.id": "/custom/metrics/up0",
            "RXBytes": 1024,
            "CXL": {"BackpressureAveragePercentage": 2.5},
        }
    )

    monkeypatch.setattr(client._systems, "processors", lambda system_id=None: [processor])
    monkeypatch.setattr(client._chassis, "pcie_devices", lambda chassis_id=None: [pcie_device])

    collection_calls = []
    collections = {
        "/custom/processor-port-index": [processor_port],
        "/custom/logical-index": [logical_device],
    }

    def get_collection(path, model):
        collection_calls.append((path, model))
        return collections[path]

    linked = {
        "/custom/ports/cp0": pcie_port,
        "/custom/logical/ld0": logical_device,
    }

    def get_list(links, model):
        return [linked[link.odata_id] for link in links]

    def get(path, model):
        assert path == "/custom/metrics/up0"
        assert model is PortMetrics
        return metrics

    monkeypatch.setattr(client, "_get_collection", get_collection)
    monkeypatch.setattr(client, "_get_list", get_list)
    monkeypatch.setattr(client._http_client, "get", get)
    yield client, processor, processor_port, pcie_device, collection_calls
    client.close()


def test_traverses_only_advertised_processor_and_pcie_links(fabric_client):
    client, processor, processor_port, pcie_device, collection_calls = fabric_client

    assert client.get_processor_ports("CPU-A") == [processor_port]
    assert processor.ualink.accelerator_id == 7
    assert client.get_port_metrics("UP0").cxl.backpressure_average_percentage == 2.5
    assert client.get_cxl_logical_devices("CXL-A")[0].memory_size_mib == 4096
    assert client.get_port_cxl_logical_devices("UP0")[0].id == "LD0"
    assert client.get_connected_pcie_ports("CXL-A")[0].odata_id == "/custom/ports/cp0"
    assert pcie_device.cxl_device.max_number_logical_devices == 1
    assert [path for path, _ in collection_calls] == [
        "/custom/processor-port-index",
        "/custom/processor-port-index",
        "/custom/logical-index",
        "/custom/processor-port-index",
    ]


def test_absent_capabilities_fail_clearly_without_vendor_inference(
    fabric_client, monkeypatch
):
    client, _, _, _, _ = fabric_client
    processor = Processor.model_validate(
        {"Id": "CPU-no-ports", "Manufacturer": "UALink Example Vendor"}
    )
    pcie_device = PCIeDevice.model_validate(
        {"Id": "device-no-cxl", "Manufacturer": "CXL Example Vendor"}
    )
    monkeypatch.setattr(client._systems, "processors", lambda system_id=None: [processor])
    monkeypatch.setattr(client._chassis, "pcie_devices", lambda chassis_id=None: [pcie_device])

    with pytest.raises(RedfishNotFoundError, match="advertise Ports"):
        client.get_processor_ports()
    with pytest.raises(RedfishNotFoundError, match="CXLLogicalDevices"):
        client.get_cxl_logical_devices("device-no-cxl")
    with pytest.raises(RedfishNotFoundError, match="ConnectedPCIePorts"):
        client.get_connected_pcie_ports("device-no-cxl")


def test_port_source_must_not_mix_processor_and_pcie_device(fabric_client):
    client, _, _, _, _ = fabric_client

    with pytest.raises(RedfishValidationError, match="either processor_id"):
        client.get_port_metrics(
            "UP0", processor_id="CPU-A", pcie_device_id="CXL-A"
        )


def test_public_port_model_export_is_stable():
    assert Port is PortModel
