"""
Update service manager — manages firmware updates.

Provides:
- Firmware inventory listing
- Software inventory and update-capability discovery
- Standards-based image staging and activation
- Client certificate listing
- Firmware update (SimpleUpdate) with multi-vendor strategy support

"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from urllib.parse import urlsplit

import requests

from ..exceptions import RedfishValidationError
from ..models.common import Link, RedfishResponse
from ..models.update import (
    ClientCertificate,
    FirmwareInventory,
    FirmwareUpdateResponse,
    SoftwareInventory,
    UpdateParameters,
    UpdateServiceCapabilities,
)
from .update_strategies import UpdateStrategyRegistry, VendorDetector

if TYPE_CHECKING:
    from ..client import RedfishClient

logger = logging.getLogger(__name__)


class UpdateServiceManager:
    """
    Manages Redfish Update service resources.

    SimpleUpdate automatically detects the server vendor and applies
    the appropriate request body format. Users can override the vendor
    detection by passing the ``vendor`` parameter.
    """

    def __init__(self, client: RedfishClient):
        self._client = client
        self._http = client._http_client

    def firmware_inventory(self) -> List[FirmwareInventory]:
        """
        Get the list of firmware inventory entries.

        """
        update_service = self._client._get_update_service()
        return self._client._get_collection(
            update_service.firmware_inventory.odata_id, FirmwareInventory
        )

    def software_inventory(self) -> List[SoftwareInventory]:
        """Get software images through the link advertised by UpdateService."""
        service = self._client._get_update_service()
        if not service.software_inventory or not service.software_inventory.odata_id:
            raise RedfishValidationError("UpdateService does not advertise SoftwareInventory")
        return self._client._get_collection(service.software_inventory.odata_id, SoftwareInventory)

    def capabilities(self) -> UpdateServiceCapabilities:
        """Get the optional standard UpdateServiceCapabilities resource."""
        service = self._client._get_update_service()
        link = service.update_service_capabilities
        if not link or not link.odata_id:
            raise RedfishValidationError("UpdateService does not advertise UpdateServiceCapabilities")
        return self._http.get(link.odata_id, UpdateServiceCapabilities)

    def client_certificates(self) -> List[ClientCertificate]:
        """
        Get the list of client certificates for firmware update authentication.

        """
        update_service = self._client._get_update_service()
        return self._client._get_collection(
            update_service.client_certificates.odata_id, ClientCertificate
        )

    def _action(self, name: str) -> Dict[str, Any]:
        actions = self._client._get_update_service().actions or {}
        matches = []

        def discover(container):
            for key, value in container.items():
                if not isinstance(value, dict):
                    continue
                if key.startswith("#") and key.endswith(f".{name}"):
                    matches.append(value)
                elif not key.startswith("#"):
                    discover(value)

        discover(actions)
        if len(matches) != 1 or not isinstance(matches[0].get("target"), str) or not matches[0]["target"]:
            raise RedfishValidationError(f"UpdateService does not advertise a unique {name} action target")
        return matches[0]

    def _allowed(self, action: Dict[str, Any], name: str, fallback: List[str]) -> List[str]:
        allowed = action.get(f"{name}@Redfish.AllowableValues")
        if allowed is None and action.get("@Redfish.ActionInfo"):
            info = self._http.get_raw(action["@Redfish.ActionInfo"])
            for parameter in info.get("Parameters", []):
                if parameter.get("Name") == name:
                    allowed = parameter.get("AllowableValues")
                    break
        return fallback if allowed is None else allowed

    def _result(self, response: requests.Response) -> FirmwareUpdateResponse:
        result = self._http._parse(response, FirmwareUpdateResponse) if response.text.strip() else FirmwareUpdateResponse()
        result.task_monitor = response.headers.get("Location") or result.task_monitor
        result.http_status = response.status_code
        result.task_uri = result.odata_id or result.task_uri
        result.retry_after = response.headers.get("Retry-After") or result.retry_after
        return result

    def _upload(
        self, target: str, file_path: Union[str, Path], field: str,
        fields: Optional[Dict[str, Any]] = None,
    ) -> FirmwareUpdateResponse:
        path = Path(file_path)
        with path.open("rb") as image:
            response = self._http.post_multipart(
                target, {field: (path.name, image, "application/octet-stream")}, fields
            )
        return self._result(response)

    def upload_sign_key(self, file_path: Union[str, Path]) -> FirmwareUpdateResponse:
        action = self._action("UploadSignKey")
        return self._upload(action["target"], file_path, "pem_file")

    def upload_firmware_image(self, file_path: Union[str, Path]) -> FirmwareUpdateResponse:
        action = self._action("UploadFirmwareImage")
        return self._upload(action["target"], file_path, "image_file")

    def upload_firmware_file(
        self,
        file_path: Union[str, Path],
        *,
        field_name: str = "UpdateFile",
        update_parameters: Optional[Union[UpdateParameters, Dict[str, Any]]] = None,
        oem_parameters: Optional[Dict[str, Any]] = None,
    ) -> FirmwareUpdateResponse:
        service = self._client._get_update_service()
        target = service.multi_part_http_push_uri or service.http_push_uri
        if not target:
            raise RedfishValidationError("UpdateService does not advertise MultipartHttpPushUri or HttpPushUri")
        fields = {}
        serialized_parameters: Dict[str, Any]
        if isinstance(update_parameters, UpdateParameters):
            serialized_parameters = self.validate_update_parameters(update_parameters).model_dump(
                by_alias=True, exclude_none=True
            )
        else:
            # Retain the existing untyped dictionary API for OEM payloads.
            serialized_parameters = update_parameters or {}
        if service.multi_part_http_push_uri or update_parameters is not None:
            fields["UpdateParameters"] = (
                None,
                json.dumps(serialized_parameters),
                "application/json",
            )
        if oem_parameters is not None:
            fields["OemParameters"] = (
                None,
                json.dumps(oem_parameters),
                "application/json",
            )
        return self._upload(target, file_path, field_name, fields)

    def bmc_firmware_update(
        self, flash_type: str = "FULLFwUpdate", upload_selector: Optional[str] = None
    ) -> FirmwareUpdateResponse:
        action = self._action("BMCFwUpdate")
        allowed = self._allowed(action, "FlashType", ["FULLFwUpdate", "DUALIMAGEFwUpdate"])
        if flash_type not in allowed:
            raise RedfishValidationError(f"Unsupported FlashType {flash_type!r}; allowable values: {allowed}")
        if flash_type == "DUALIMAGEFwUpdate" and not upload_selector:
            raise RedfishValidationError("UploadSelector is required for DUALIMAGEFwUpdate")
        body = {"FlashType": flash_type}
        if upload_selector is not None:
            selectors = self._allowed(action, "UploadSelector", ["AutoInactive", "Image1", "Image2", "ImageBoth"])
            if upload_selector not in selectors:
                raise RedfishValidationError(f"Unsupported UploadSelector {upload_selector!r}; allowable values: {selectors}")
            body["UploadSelector"] = upload_selector
        return self._result(self._http.post_raw(action["target"], body))

    def build_update_parameters(
        self,
        *,
        targets: Optional[List[str]] = None,
        exclude_targets: Optional[List[str]] = None,
        force_update: Optional[bool] = None,
        stage: Optional[bool] = None,
        local_image: Optional[bool] = None,
        oem: Optional[Dict[str, Any]] = None,
    ) -> UpdateParameters:
        """Build and validate standard parameters against advertised support."""
        return self.validate_update_parameters(
            UpdateParameters(
                targets=targets,
                exclude_targets=exclude_targets,
                force_update=force_update,
                stage=stage,
                local_image=local_image,
                oem=oem,
            )
        )

    def validate_update_parameters(self, parameters: UpdateParameters) -> UpdateParameters:
        """Reject requested parameters that the service does not advertise."""
        requested = {
            "Targets": parameters.targets,
            "ExcludeTargets": parameters.exclude_targets,
            "ForceUpdate": parameters.force_update,
            "Stage": parameters.stage,
            "LocalImage": parameters.local_image,
        }
        if all(value is None for value in requested.values()):
            return parameters

        capabilities = self.capabilities()
        support = {
            "Targets": capabilities.targets_parameter_supported,
            "ExcludeTargets": capabilities.exclude_targets_parameter_supported,
            "ForceUpdate": capabilities.force_update_parameter_supported,
            "Stage": capabilities.stage_parameter_supported,
            "LocalImage": capabilities.local_image_parameter_supported,
        }
        # UpdateServiceCapabilities v1.0 predates the explicit support flags.
        if support["Targets"] is None and (
            capabilities.allowable_targets is not None or capabilities.allowable_target_reference_types
        ):
            support["Targets"] = True
        if support["Stage"] is None and capabilities.allowable_staging is not None:
            support["Stage"] = True

        for name, value in requested.items():
            if value is not None and support[name] is not True:
                raise RedfishValidationError(f"UpdateServiceCapabilities does not advertise {name} support")

        if parameters.targets:
            if parameters.stage is True:
                allowable = capabilities.allowable_staging or []
                rejected = [target for target in parameters.targets if target not in allowable]
                if rejected:
                    raise RedfishValidationError(f"Targets {rejected} are not advertised in AllowableStaging")
            else:
                for target in parameters.targets:
                    self._validate_target_reference(target, capabilities)
        return parameters

    def _validate_target_reference(self, target: str, capabilities: UpdateServiceCapabilities) -> None:
        if target in (capabilities.allowable_targets or []):
            return
        allowed_types = capabilities.allowable_target_reference_types or []
        if not allowed_types:
            raise RedfishValidationError(f"Target {target!r} is not advertised in AllowableTargets")
        resource = self._http.get_raw(target)
        odata_type = str(resource.get("@odata.type", ""))
        resource_type = odata_type.rsplit(".", 1)[-1]
        reference_type = self._target_reference_type(resource_type)
        if reference_type not in allowed_types:
            raise RedfishValidationError(
                f"Target {target!r} has unsupported target reference type "
                f"{reference_type or resource_type or 'unknown'!r}; "
                f"allowable values: {allowed_types}"
            )

    @staticmethod
    def _target_reference_type(resource_type: str) -> Optional[str]:
        if resource_type in {"SoftwareInventory", "ComputerSystem", "Aggregate"}:
            return resource_type
        if resource_type.endswith("Collection"):
            return "ResourceCollection"
        device_resources = {
            "Assembly",
            "Drive",
            "FabricAdapter",
            "Memory",
            "MemoryChunks",
            "NetworkAdapter",
            "NetworkDeviceFunction",
            "PCIeDevice",
            "PCIeFunction",
            "Processor",
            "Storage",
            "StorageController",
            "Switch",
        }
        return "DeviceResource" if resource_type in device_resources else None

    def standard_simple_update(
        self,
        image_uri: str,
        transfer_protocol: str = "HTTP",
        *,
        parameters: Optional[UpdateParameters] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> FirmwareUpdateResponse:
        """Invoke the standard SimpleUpdate action without OEM translation."""
        action = self._action("SimpleUpdate")
        validated = self.validate_update_parameters(parameters or UpdateParameters())
        body: Dict[str, Any] = {
            "ImageURI": image_uri,
            "TransferProtocol": transfer_protocol,
        }
        body.update(validated.model_dump(by_alias=True, exclude_none=True))
        if username is not None:
            body["Username"] = username
        if password is not None:
            body["Password"] = password
        return self._result(self._http.post_raw(action["target"], body))

    def stage_update(
        self,
        image_uri: str,
        targets: List[str],
        transfer_protocol: Optional[str] = None,
        *,
        force_update: Optional[bool] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> FirmwareUpdateResponse:
        """Stage an image on advertised targets for a later apply operation."""
        protocol = transfer_protocol or urlsplit(image_uri).scheme.upper() or "HTTP"
        parameters = self.build_update_parameters(targets=targets, stage=True, force_update=force_update)
        return self.standard_simple_update(
            image_uri,
            protocol,
            parameters=parameters,
            username=username,
            password=password,
        )

    def activate_software(self, targets: List[Union[str, Link]]) -> FirmwareUpdateResponse:
        """Activate staged SoftwareInventory resources through UpdateService."""
        action = self._action("Activate")
        links = []
        for target in targets:
            uri = target if isinstance(target, str) else target.odata_id
            if not uri:
                raise RedfishValidationError("Activate targets must contain non-empty Redfish URIs")
            links.append({"@odata.id": uri})
        if not links:
            raise RedfishValidationError("Activate requires at least one target")
        return self._result(self._http.post_raw(action["target"], {"Targets": links}))

    def simple_update(
        self,
        image_uri: str,
        transfer_protocol: str = "HTTP",
        targets: Optional[list] = None,
        vendor: Optional[str] = None,
        **kwargs: Any,
    ) -> RedfishResponse:
        """
        Trigger a firmware update via a remote image URI (e.g., NFS, HTTP).

        Automatically detects the server vendor and uses the appropriate
        request body format. The vendor can be manually overridden.

        Args:
            image_uri: URI of the firmware image (e.g., "http://nas/fw/bmc.bin")
            transfer_protocol: Transfer protocol (e.g., "HTTP", "NFS", "TFTP")
            targets: Optional list of firmware target paths
                     (e.g., ["/redfish/v1/Managers/Self"] or ["ActiveBMC"])
            vendor: Optional vendor override (e.g., "inspur", "lenovo").
                    If not set, the vendor is auto-detected.
            **kwargs: Vendor-specific parameters. Common ones include:
                - username (str): File server username (Inspur, Lenovo, H3C)
                - password (str): File server password (Inspur, Lenovo, H3C)
                - preserve_config (bool): Preserve configuration during update

        Returns:
            RedfishResponse (may contain a task reference for async update)
        """
        detected_vendor = vendor or VendorDetector.detect(self._client)
        strategy = UpdateStrategyRegistry.get(detected_vendor)

        logger.info(
            "SimpleUpdate: vendor=%s, strategy=%s, ImageURI=%s",
            detected_vendor,
            type(strategy).__name__,
            image_uri,
        )

        return strategy.execute(
            self._client, image_uri, transfer_protocol, targets, **kwargs
        )
