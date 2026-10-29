"""Modern chassis power resources with explicit legacy fallbacks."""

import json
from pathlib import Path

import pytest

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import RedfishNotFoundError
from redfish_sdk.models.chassis import Chassis
from redfish_sdk.models.cooling import EnvironmentMetrics, Sensor
from redfish_sdk.models.power import (
    Power,
    PowerSubsystem,
    PowerSupply,
    PowerSupplyMetrics,
)

TESTDATA_DIR = Path(__file__).parent.parent / "testdata"


def _fixtures() -> dict:
    with (TESTDATA_DIR / "power_subsystem.json").open(
        encoding="utf-8"
    ) as fixture:
        return json.load(fixture)


@pytest.fixture
def power_client(monkeypatch):
    fixtures = _fixtures()
    client = RedfishClient(host="mock-bmc", username="user", password="password")
    chassis = Chassis.model_validate(fixtures["ModernChassis"])
    resources = {
        "/vendor/power-domain": (PowerSubsystem, fixtures["PowerSubsystem"]),
        "/vendor/psu-A": (PowerSupply, fixtures["ModernPowerSupply"]),
        "/vendor/psu-A/telemetry": (
            PowerSupplyMetrics,
            fixtures["PowerSupplyMetrics"],
        ),
        "/vendor/environment": (
            EnvironmentMetrics,
            fixtures["EnvironmentMetrics"],
        ),
        "/vendor/sensors/brake-load": (Sensor, fixtures["BrakeLoadSensor"]),
        "/vendor/sensors/brake-temperature": (
            Sensor,
            fixtures["BrakeTemperatureSensor"],
        ),
        "/legacy/power": (Power, fixtures["LegacyPower"]),
    }
    collections = {
        "/vendor/psu-index": ["/vendor/psu-A"],
        "/vendor/sensor-index": [
            "/vendor/sensors/brake-load",
            "/vendor/sensors/brake-temperature",
        ],
    }
    requested = []

    monkeypatch.setattr(client._chassis, "get", lambda chassis_id=None: chassis)

    def get(path, model):
        requested.append(path)
        expected_model, payload = resources[path]
        assert model is expected_model
        return model.model_validate(payload)

    def get_collection(path, model):
        requested.append(path)
        return [get(member, model) for member in collections[path]]

    monkeypatch.setattr(client._http_client, "get", get)
    monkeypatch.setattr(client, "_get_collection", get_collection)
    yield client, chassis, requested, fixtures
    client.close()


def test_modern_power_models_include_brake_ramp_metrics_and_oem(power_client):
    client, _, _, _ = power_client

    subsystem = client.get_power_subsystem()
    supplies = client.get_power_supplies()
    metrics = client.get_power_supply_metrics("PSU-A")

    assert subsystem.capacity_watts == 3200
    assert subsystem.max_ramp_rate_watts_per_second.reading == 450
    assert subsystem.power_brake.applied is True
    assert subsystem.power_brake.load_percent_threshold == "UpperCaution"
    assert (
        subsystem.links.power_brake_load_percent_sensor.odata_id
        == "/vendor/sensors/brake-load"
    )
    assert supplies[0].power_supply_type == "DCRegulator"
    assert supplies[0].metrics.odata_id == "/vendor/psu-A/telemetry"
    assert metrics.power_load_percent.reading == 62.5
    assert metrics.charge_percent.reading == 88
    assert metrics.input_power_watts.reading == 1250
    assert metrics.model_extra["FutureMetric"]["Reading"] == 1


def test_power_resources_follow_nonstandard_advertised_paths(power_client):
    client, _, requested, _ = power_client

    assert client.get_power_supply("PSU-A").id == "PSU-A"
    assert client.get_power_supply_metrics("PSU-A").id == "PSU-A-Metrics"

    assert "/vendor/power-domain" in requested
    assert "/vendor/psu-index" in requested
    assert "/vendor/psu-A" in requested
    assert "/vendor/psu-A/telemetry" in requested
    assert not any("PowerSubsystem/PowerSupplies" in path for path in requested)


def test_modern_environment_and_sensor_readings_are_typed(power_client):
    client, _, _, _ = power_client

    environment = client.get_environment_metrics()
    sensors = client.get_sensors()

    assert environment.current_amps.reading == 5.2
    assert environment.energy_kwh.reading == 123.4
    assert environment.power_watts.reading == 1180
    assert environment.power_limit_watts.set_point == 1500
    assert sensors[0].load_percent == 62.5
    assert sensors[1].average_reading == 36.5
    assert sensors[1].model_extra["FutureSensorField"] == "preserved"


@pytest.mark.parametrize("power_supply_type", ["AC", "DC", "ACorDC"])
def test_legacy_power_supply_types_remain_usable(power_supply_type):
    payload = _fixtures()["LegacyPowerSupply"] | {
        "PowerSupplyType": power_supply_type
    }

    assert PowerSupply.model_validate(payload).power_supply_type == power_supply_type


def test_legacy_only_chassis_falls_back_to_embedded_power(power_client):
    client, chassis, requested, fixtures = power_client
    legacy = Chassis.model_validate(fixtures["LegacyChassis"])
    chassis.power_subsystem = legacy.power_subsystem
    chassis.power = legacy.power

    supplies = client.get_power_supplies()

    assert [supply.member_id for supply in supplies] == ["LegacyPSU1"]
    assert client.get_power_supply("LegacyPSU1").member_id == "LegacyPSU1"
    assert "/legacy/power" in requested
    assert "/vendor/power-domain" not in requested


def test_modern_only_chassis_does_not_require_legacy_power(power_client):
    client, chassis, requested, _ = power_client
    chassis.power = None

    supplies = client.get_power_supplies()

    assert [supply.id for supply in supplies] == ["PSU-A"]
    assert "/vendor/psu-index" in requested
    assert "/legacy/power" not in requested


def test_mixed_chassis_prefers_modern_power_resources(power_client):
    client, _, requested, _ = power_client

    supplies = client.get_power_supplies()

    assert [supply.id for supply in supplies] == ["PSU-A"]
    assert "/vendor/psu-index" in requested
    assert "/legacy/power" not in requested


def test_absent_power_capabilities_are_explicit(power_client):
    client, chassis, _, fixtures = power_client
    absent = Chassis.model_validate(fixtures["AbsentChassis"])
    chassis.power_subsystem = absent.power_subsystem
    chassis.power = absent.power

    with pytest.raises(RedfishNotFoundError, match="PowerSubsystem"):
        client.get_power_subsystem()
    assert client.get_power_supplies() == []
    with pytest.raises(RedfishNotFoundError, match="PowerSupplyMetrics"):
        client.get_power_supply_metrics("PSU-A")


def test_read_only_power_measurements_do_not_invoke_actions(power_client):
    client, _, _, _ = power_client

    client._http_client.post = pytest.fail
    client._http_client.patch = pytest.fail
    client._http_client.patch_raw = pytest.fail

    client.get_power_subsystem()
    client.get_power_supplies()
    client.get_power_supply_metrics("PSU-A")
