"""Optional liquid-cooling resources follow service-advertised links."""

from __future__ import annotations

import json

import pytest
import requests

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishNotFoundError
from redfish_sdk.models.chassis import Chassis
from redfish_sdk.models.cooling import CoolantConnector, CoolingUnit, Fan, Sensor


@pytest.fixture
def cooling_client(monkeypatch):
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    chassis = Chassis.model_validate(
        {
            "Id": "Rack",
            "@odata.id": "/redfish/v1/Chassis/Rack",
            "EnvironmentMetrics": {"@odata.id": "/vendor/rack-metrics"},
            "Sensors": {"@odata.id": "/vendor/sensor-index"},
            "ThermalSubsystem": {"@odata.id": "/vendor/thermal"},
            "Links": {
                "CoolingUnits": [
                    {"@odata.id": "/vendor/cdu/primary"},
                    {"@odata.id": "/vendor/cdu-collection"},
                ]
            },
        }
    )
    resources = {
        "/vendor/rack-metrics": {
            "Id": "Metrics",
            "@odata.id": "/vendor/rack-metrics",
            "AmbientTemperatureCelsius": {"Reading": 24.5, "DataSourceUri": "/vendor/sensors/ambient"},
        },
        "/vendor/sensors/ambient": {
            "Id": "ambient",
            "@odata.id": "/vendor/sensors/ambient",
            "Reading": 24.5,
            "ReadingType": "Temperature",
            "ReadingUnits": "Cel",
        },
        "/vendor/sensors/conductivity": {
            "Id": "conductivity",
            "@odata.id": "/vendor/sensors/conductivity",
            "Reading": 0.42,
            "ReadingType": "LiquidConductivity",
            "ReadingUnits": "mS/cm",
        },
        "/vendor/cdu/primary": {
            "Id": "CDU-1",
            "@odata.id": "/vendor/cdu/primary",
            "EquipmentType": "CDU",
            "SparePartNumber": "SP-CDU-1",
            "EnvironmentMetrics": {"@odata.id": "/vendor/cdu/metrics"},
            "PrimaryCoolantConnectors": {"@odata.id": "/vendor/connectors/primary"},
        },
        "/vendor/cdu/secondary": {
            "Id": "CDU-2",
            "@odata.id": "/vendor/cdu/secondary",
            "EquipmentType": "HeatExchanger",
        },
        "/vendor/cdu/metrics": {
            "Id": "CDU-Metrics",
            "@odata.id": "/vendor/cdu/metrics",
            "TemperatureCelsius": {"Reading": 20.0},
        },
        "/vendor/thermal": {
            "Id": "Thermal",
            "@odata.id": "/vendor/thermal",
            "CoolantConnectors": {"@odata.id": "/vendor/connectors/chassis"},
        },
        "/vendor/connectors/supply": {
            "Id": "Supply",
            "@odata.id": "/vendor/connectors/supply",
            "ConductivityMSPerCm": {
                "Reading": 0.42,
                "DataSourceUri": "/vendor/sensors/conductivity",
            },
            "pH": {"Reading": 7.2},
            "TurbidityNTU": {"Reading": 0.1},
        },
    }
    collections = {
        "/vendor/sensor-index": [
            "/vendor/sensors/ambient",
            "/vendor/sensors/conductivity",
        ],
        "/vendor/cdu-collection": ["/vendor/cdu/secondary"],
        "/vendor/connectors/chassis": ["/vendor/connectors/supply"],
        "/vendor/connectors/primary": ["/vendor/connectors/supply"],
    }
    monkeypatch.setattr(client._chassis, "get", lambda chassis_id=None: chassis)

    def get_raw(path):
        if path in collections:
            return {"Members": [{"@odata.id": member} for member in collections[path]]}
        return resources[path]

    def request(method, path, **kwargs):
        assert method == "GET"
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(resources[path]).encode()
        return response

    monkeypatch.setattr(client._http_client, "get_raw", get_raw)
    monkeypatch.setattr(client._http_client, "_request", request)
    yield client, chassis
    client.close()


def test_fluid_models_preserve_readings_units_and_older_payloads():
    connector = CoolantConnector.model_validate(
        {
            "ConductivityMSPerCm": {"Reading": 0.42},
            "pH": {"Reading": 7.2},
            "TurbidityNTU": {"Reading": 0.1},
            "FutureFluidProperty": {"Reading": 1},
        }
    )
    sensor = Sensor.model_validate(
        {"Reading": 0.42, "ReadingType": "LiquidConductivity", "ReadingUnits": "mS/cm"}
    )
    older_unit = CoolingUnit.model_validate({"EquipmentType": "CDU"})

    assert connector.conductivity_ms_per_cm.reading == 0.42
    assert connector.ph.reading == 7.2
    assert connector.turbidity_ntu.reading == 0.1
    assert connector.model_extra["FutureFluidProperty"] == {"Reading": 1}
    assert sensor.reading_type == "LiquidConductivity"
    assert sensor.reading_units == "mS/cm"
    assert older_unit.spare_part_number is None


def test_standalone_fan_parses_speed_rpm_and_inventory_fields():
    fan = Fan.model_validate({
        "@odata.id": "/redfish/v1/Chassis/Self/ThermalSubsystem/Fans/160",
        "Id": "160",
        "Name": "Fan 160",
        "Manufacturer": "Contoso",
        "Model": "FAN-12K",
        "PhysicalContext": "Chassis",
        "SpeedPercent": {
            "SpeedRPM": 7500,
            "DataSourceUri": "/redfish/v1/Chassis/Self/Sensors/Fan160",
        },
        "Status": {"State": "Enabled", "Health": "OK"},
    })

    assert fan.speed_percent.speed_rpm == 7500
    assert fan.speed_percent.data_source_uri.endswith("/Sensors/Fan160")
    assert fan.manufacturer == "Contoso"
    assert fan.status.health == "OK"


def test_standalone_fan_parses_speed_percent_reading():
    fan = Fan.model_validate({
        "Id": "160",
        "SpeedPercent": {"Reading": 62.5},
    })

    assert fan.speed_percent.reading == 62.5
    assert fan.speed_percent.speed_rpm is None


def test_standalone_fan_parses_location_and_cooling_chassis_links():
    fan = Fan.model_validate({
        "Id": "Bay1",
        "LocationIndicatorActive": True,
        "HotPluggable": True,
        "Location": {
            "PartLocation": {
                "ServiceLabel": "Chassis Fan Bay 1",
                "LocationType": "Bay",
                "LocationOrdinalValue": 1,
            }
        },
        "Links": {
            "CoolingChassis": [
                {"@odata.id": "/redfish/v1/Chassis/Self"},
            ]
        },
    })

    assert fan.location_indicator_active is True
    assert fan.hot_pluggable is True
    assert fan.location.part_location.service_label == "Chassis Fan Bay 1"
    assert fan.links.cooling_chassis[0].odata_id == "/redfish/v1/Chassis/Self"


@pytest.mark.parametrize(
    ("reading_type", "units"),
    [
        ("LiquidConductivity", "mS/cm"),
        ("pH", "pH"),
        ("Turbidity", "[NTU]"),
    ],
)
def test_liquid_sensor_reading_types_and_units(reading_type, units):
    sensor = Sensor.model_validate(
        {"Reading": 1.0, "ReadingType": reading_type, "ReadingUnits": units}
    )

    assert sensor.reading_type == reading_type
    assert sensor.reading_units == units


def test_discovers_cooling_units_from_direct_and_collection_links(cooling_client):
    client, _ = cooling_client

    units = client.get_cooling_units()

    assert [(unit.id, unit.equipment_type) for unit in units] == [
        ("CDU-1", "CDU"),
        ("CDU-2", "HeatExchanger"),
    ]
    assert units[0].spare_part_number == "SP-CDU-1"


def test_discovers_fluid_measurements_and_sensor_units(cooling_client):
    client, _ = cooling_client

    connector = client.get_coolant_connectors()[0]
    unit_connector = client.get_coolant_connectors(cooling_unit_id="CDU-1")[0]
    sensors = client.get_sensors()

    assert connector.conductivity_ms_per_cm.reading == 0.42
    assert connector.ph.reading == 7.2
    assert connector.turbidity_ntu.reading == 0.1
    assert unit_connector.odata_id == connector.odata_id
    assert client.get_sensor("conductivity").reading_units == "mS/cm"
    assert {sensor.reading_type for sensor in sensors} == {
        "Temperature",
        "LiquidConductivity",
    }


def test_environment_metrics_follow_chassis_or_cooling_unit_link(cooling_client):
    client, _ = cooling_client

    chassis_metrics = client.get_environment_metrics()
    unit_metrics = client.get_environment_metrics(cooling_unit_id="CDU-1")

    assert chassis_metrics.ambient_temperature_celsius.reading == 24.5
    assert unit_metrics.temperature_celsius.reading == 20.0


@pytest.mark.parametrize(
    ("field", "method", "message"),
    [
        ("sensors", "get_sensors", "Sensors"),
        ("environment_metrics", "get_environment_metrics", "EnvironmentMetrics"),
        ("thermal_subsystem", "get_coolant_connectors", "CoolantConnectors"),
    ],
)
def test_missing_optional_cooling_capability_fails_clearly(
    cooling_client, field, method, message
):
    client, chassis = cooling_client
    setattr(chassis, field, None)
    if field == "thermal_subsystem":
        chassis.links.cooling_units = None

    with pytest.raises(RedfishNotFoundError, match=message):
        getattr(client, method)()


def test_missing_cooling_units_preserves_ordinary_chassis(cooling_client):
    client, chassis = cooling_client
    chassis.links.cooling_units = None

    with pytest.raises(RedfishNotFoundError, match="CoolingUnits"):
        client.get_cooling_units()

    assert client.get_chassis().id == "Rack"
