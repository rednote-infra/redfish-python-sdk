"""Read-only discovery for optional Redfish liquid-cooling resources."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Type, TypeVar

from ..exceptions import RedfishNotFoundError
from ..models.common import Entity, Link
from ..models.cooling import (
    CoolantConnector,
    CoolingUnit,
    EnvironmentMetrics,
    Sensor,
    ThermalSubsystem,
)
from .system_resources import select_member, unique_members

if TYPE_CHECKING:
    from ..client import RedfishClient
    from ..models.chassis import Chassis

CoolingResource = TypeVar("CoolingResource", bound=Entity)


class CoolingManager:
    """Discovers cooling resources only through links advertised by the service."""

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def _resources_from_links(
        self, links: List[Link], model: Type[CoolingResource]
    ) -> List[CoolingResource]:
        resources: List[CoolingResource] = []
        for link in links:
            if not link.odata_id:
                continue
            payload = self._http.get_raw(link.odata_id)
            members = payload.get("Members")
            if isinstance(members, list):
                for member in members:
                    odata_id = member.get("@odata.id") if isinstance(member, dict) else None
                    if odata_id:
                        resources.append(self._http.get(odata_id, model))
            else:
                resources.append(model.model_validate(payload))
        return unique_members(resources)

    @staticmethod
    def _cooling_unit_links(chassis: Chassis) -> List[Link]:
        return list(chassis.links.cooling_units or []) if chassis.links else []

    def _cooling_units(self, chassis: Chassis) -> List[CoolingUnit]:
        links = self._cooling_unit_links(chassis)
        return self._resources_from_links(links, CoolingUnit) if links else []

    def cooling_units(self, chassis_id: Optional[str] = None) -> List[CoolingUnit]:
        chassis = self._client._chassis.get(chassis_id)
        units = self._cooling_units(chassis)
        if not self._cooling_unit_links(chassis):
            raise RedfishNotFoundError("Chassis does not advertise CoolingUnits")
        return units

    def coolant_connectors(
        self,
        cooling_unit_id: Optional[str] = None,
        chassis_id: Optional[str] = None,
    ) -> List[CoolantConnector]:
        chassis = self._client._chassis.get(chassis_id)
        connector_links: List[Link] = []

        if (
            cooling_unit_id is None
            and chassis.thermal_subsystem
            and chassis.thermal_subsystem.odata_id
        ):
            subsystem = self._http.get(
                chassis.thermal_subsystem.odata_id, ThermalSubsystem
            )
            if subsystem.coolant_connectors:
                connector_links.append(subsystem.coolant_connectors)

        units = self._cooling_units(chassis)
        if cooling_unit_id is not None:
            if not self._cooling_unit_links(chassis):
                raise RedfishNotFoundError("Chassis does not advertise CoolingUnits")
            units = [select_member(units, cooling_unit_id)]
        for unit in units:
            if unit.primary_coolant_connectors:
                connector_links.append(unit.primary_coolant_connectors)
            if unit.secondary_coolant_connectors:
                connector_links.append(unit.secondary_coolant_connectors)

        if not connector_links:
            raise RedfishNotFoundError(
                "Chassis and CoolingUnits do not advertise CoolantConnectors"
            )
        return self._resources_from_links(connector_links, CoolantConnector)

    def sensors(self, chassis_id: Optional[str] = None) -> List[Sensor]:
        chassis = self._client._chassis.get(chassis_id)
        if not chassis.sensors or not chassis.sensors.odata_id:
            raise RedfishNotFoundError("Chassis does not advertise Sensors")
        return self._client._get_collection(chassis.sensors.odata_id, Sensor)

    def sensor(self, identifier: str, chassis_id: Optional[str] = None) -> Sensor:
        return select_member(self.sensors(chassis_id), identifier)

    def environment_metrics(
        self,
        cooling_unit_id: Optional[str] = None,
        chassis_id: Optional[str] = None,
    ) -> EnvironmentMetrics:
        chassis = self._client._chassis.get(chassis_id)
        if cooling_unit_id is None:
            link = chassis.environment_metrics
            owner = "Chassis"
        else:
            if not self._cooling_unit_links(chassis):
                raise RedfishNotFoundError("Chassis does not advertise CoolingUnits")
            units = self._cooling_units(chassis)
            unit = select_member(units, cooling_unit_id)
            link = unit.environment_metrics
            owner = "CoolingUnit"
        if not link or not link.odata_id:
            raise RedfishNotFoundError(f"{owner} does not advertise EnvironmentMetrics")
        return self._http.get(link.odata_id, EnvironmentMetrics)
