"""
Firewall (OEM extension) resource models.

DMTF Redfish defines no generic Manager firewall resource. AMI MegaRAC /
Enginetech BMCs expose an OEM navigation container which links to three
collections: ``FirewallConfig``, ``IPRules`` and ``PortRules``. The container
is discovered from the Manager's OEM block, e.g. ``Oem.Firewall`` or
``Oem.Ami.Firewall``.

The models here are intentionally permissive — every field is optional and
``extra="allow"`` is inherited from :class:`Entity` — so that a single model
can absorb the shapes seen across vendors:

* Enginetech — root resource carrying three sub-collection links.
* Legacy — the firewall resource itself is a plain ``Members`` collection.
* SecurityService-style — root resource carrying ``ActiveStrategy`` / ``Rules``.

Read-only: mutation helpers are out of scope for this release.
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import Entity, Link


class FirewallTimeout(BaseModel):
    """
    Time window during which a firewall rule / configuration is active.

    Timestamps carry no timezone information and no consistent precision
    (``"2026-08-27 10:00:00"`` vs ``"2026-08-05 00:00"``), so they are kept as
    raw strings — callers parse them with whatever tolerance they need.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    start_time: Optional[str] = Field(None, alias="StartTime")
    stop_time: Optional[str] = Field(None, alias="StopTime")


class Firewall(Entity):
    """
    Firewall root resource for a manager (BMC).

    AMI MegaRAC / Enginetech OEM extension, dynamically discovered from the
    Manager's OEM block. Typical endpoints:
    ``/redfish/v1/Managers/{managerId}/Oem/Firewall`` and
    ``/redfish/v1/Managers/{managerId}/Oem/Ami/Firewall``

    DMTF Redfish has no generic Manager firewall resource: this is a
    navigation container pointing at three collections (``FirewallConfig``,
    ``IPRules``, ``PortRules``).  Read the actual rules through
    :meth:`RedfishClient.get_firewall_ip_rules` and friends.

    ``Members`` / ``Members@odata.count`` / ``ActiveStrategy`` / ``Rules`` are
    kept for compatibility with vendors whose firewall resource is not a
    navigation container; they stay ``None`` on Enginetech BMCs.
    """
    # Enginetech 形态：三个子集合导航链接
    firewall_config: Optional[Link] = Field(None, alias="FirewallConfig")
    ip_rules: Optional[Link] = Field(None, alias="IPRules")
    port_rules: Optional[Link] = Field(None, alias="PortRules")

    # 兼容：部分厂商把防火墙资源本身做成集合
    members: Optional[List[Link]] = Field(None, alias="Members")
    members_count: Optional[int] = Field(None, alias="Members@odata.count")

    # 兼容：SecurityService/FirewallRules 形态（ActiveStrategy + Rules）
    active_strategy: Optional[str] = Field(None, alias="ActiveStrategy")
    rules: Optional[List[Any]] = Field(None, alias="Rules")


class FirewallRule(Entity):
    """
    A single firewall rule entry.

    Superset of the fields seen on ``FirewallConfig`` / ``IPRules`` /
    ``PortRules`` members.  Every field is optional because each rule type only
    carries its own subset — an IP rule has no ``Port1``, a port rule has no
    ``IPAddress1``, and so on.

    ``Type`` is assigned by the BMC on creation and is therefore only ever
    observed on GET, never sent by the caller.
    """
    ip_version: Optional[str] = Field(None, alias="IPVersion")
    ip_address1: Optional[str] = Field(None, alias="IPAddress1")
    ip_address2: Optional[str] = Field(None, alias="IPAddress2")
    port1: Optional[int] = Field(None, alias="Port1")
    port2: Optional[int] = Field(None, alias="Port2")
    protocol: Optional[str] = Field(None, alias="Protocol")
    position: Optional[int] = Field(None, alias="Position")
    state: Optional[str] = Field(None, alias="State")
    type: Optional[str] = Field(None, alias="Type")
    timeout: Optional[FirewallTimeout] = Field(None, alias="Timeout")


class FirewallIpRule(FirewallRule):
    """Member of the Enginetech ``IPRules`` collection."""


class FirewallPortRule(FirewallRule):
    """Member of the Enginetech ``PortRules`` collection."""


class FirewallConfigEntry(FirewallRule):
    """
    Member of the Enginetech ``FirewallConfig`` collection (block-all settings).

    Unlike its siblings this resource reports its identifier as lower-case
    ``"id"`` (and a snake-case ``timeout_enabled``) while every other firewall
    collection uses ``"Id"``.  The mismatch is normalized in ``_normalize_id``
    so ``.id`` stays populated.
    """
    timeout_enabled: Optional[bool] = Field(None, alias="timeout_enabled")

    @model_validator(mode="before")
    @classmethod
    def _normalize_id(cls, data: Any) -> Any:
        """Map a lower-case ``id`` onto ``Entity.id`` (alias ``Id``)."""
        if isinstance(data, dict) and "id" in data and "Id" not in data:
            data = {**data, "Id": data["id"]}
        return data
