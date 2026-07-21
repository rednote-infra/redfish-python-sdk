"""
Processor (CPU) component models.

"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from .check import Field
from .common import Entity, Link, Status
from .oem import Oem


class ProcessorId(BaseModel):
    """CPU identification fields."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    effective_family: Optional[str] = Field(None, alias="EffectiveFamily")
    effective_model: Optional[str] = Field(None, alias="EffectiveModel")
    identification_registers: Optional[str] = Field(None, alias="IdentificationRegisters")
    microcode_info: Optional[str] = Field(None, alias="MicrocodeInfo")
    step: Optional[str] = Field(None, alias="Step")
    vendor_id: Optional[str] = Field(None, alias="VendorId")


class Processor(Entity):
    """
    Represents a CPU/processor resource.
    Endpoint: /redfish/v1/Systems/{systemId}/Processors/{processorId}

    """
    instruction_set: Optional[str] = Field(None, alias="InstructionSet")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer", validate="required,type=str")
    max_speed_mhz: Optional[int] = Field(None, alias="MaxSpeedMHz", validate="type=int,gt=0")
    model: Optional[str] = Field(None, alias="Model", validate="required,type=str")
    operating_speed_mhz: Optional[int] = Field(None, alias="OperatingSpeedMHz")
    processor_architecture: Optional[str] = Field(None, alias="ProcessorArchitecture")
    processor_id: Optional[ProcessorId] = Field(None, alias="ProcessorId")
    processor_type: Optional[str] = Field(None, alias="ProcessorType", validate="type=str")
    socket: Optional[Any] = Field(None, alias="Socket")
    total_cores: Optional[int] = Field(None, alias="TotalCores", validate="required,type=int,gt=0")
    total_threads: Optional[int] = Field(None, alias="TotalThreads", validate="required,type=int,gt=0,gte_field=total_cores")
    max_tdp_watts: Optional[int] = Field(None, alias="MaxTDPWatts")
    tdp_watts: Optional[int] = Field(None, alias="TDPWatts")
    serial_number: Optional[str] = Field(None, alias="SerialNumber")
    status: Optional[Status] = Field(None, alias="Status", validate="status")
    oem: Optional[Oem] = Field(None, alias="Oem")
    environment_metrics: Optional[Link] = Field(None, alias="EnvironmentMetrics")
