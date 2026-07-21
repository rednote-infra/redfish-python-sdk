"""
Registries manager — manages Redfish message registries.

"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from ..models.registry import Registry

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


class RegistriesManager:
    """
    Manages Redfish message registries.


    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def registries(self) -> List[Registry]:
        """
        Get the list of message registries.


        """
        return self._client._get_registries_collection()

    def get(self, registry_id: str) -> Registry:
        """
        Get a specific message registry by ID.

        Args:
            registry_id: Registry ID (e.g., "Base.1.15.0")

        Returns:
            Registry resource
        """
        registries_odata_id = self._client._get_registries_collection_odata_id()
        return self._http.get(f"{registries_odata_id}/{registry_id}", Registry)
