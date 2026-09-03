"""
Typed models used by the out-of-band diagnostic log collection strategies.

These models cover the resources that the standard ``Log`` / ``LogEntry`` /
``Task`` models don't already describe and that the collection flow needs
to read *structured* data from — so vendor strategies never have to touch
``get_raw()`` and index bare dicts.

Coverage:
    - :class:`ActionTarget`         — Redfish action ``{"target": ...}`` block.
    - :class:`LogServicesCollection`— LogServices collection with typed
                                      ``Actions.Oem`` (Inspur / ZTE publish
                                      the collection-level trigger there).
    - :class:`DiagnosticService`    — smoothcompute OEM Manager sub-resource
                                      that exposes CollectBlackBox / ExportBlackBox.
    - :class:`ZteDumpProgress`      — ZTE OEM ``LogServices.Dump/Progress``
                                      endpoint (bespoke, not a Redfish Task).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import Entity, Link


class ActionTarget(BaseModel):
    """
    A Redfish Action descriptor — the ``{"target": "...", ...}`` object that
    lives under ``Actions[<name>]``. Extra vendor fields (e.g.
    ``@Redfish.ActionInfo``, ``AllowableValues``) are preserved via
    ``extra="allow"``.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    target: Optional[str] = Field(None, alias="target")


class LogServicesCollection(Entity):
    """
    ``/redfish/v1/{Managers|Systems}/{id}/LogServices`` collection.

    Beyond the standard ``Members``, some BMCs (Inspur, ZTE) advertise the
    diagnostic-collection trigger as a *collection-level* OEM action under
    ``Actions.Oem`` — this model exposes it as a typed
    ``actions_oem: Dict[str, Dict[str, ActionTarget]]`` so strategy code
    does not have to walk raw dicts.

    ``actions_oem`` shape example (Inspur)::

        {"Public": {"#LogService.CollectAllLog": ActionTarget(target=...)}}

    ZTE and smoothcompute publish the OEM block directly, e.g.::

        {"Oem": {"#LogServices.Dump": ActionTarget(target=...)}}

    — this is normalised into ``actions_oem`` too (see the field validator on
    :meth:`_oem_actions`).
    """
    members: List[Link] = Field(default_factory=list, alias="Members")
    members_count: Optional[int] = Field(None, alias="Members@odata.count")
    #: Raw ``Actions`` block; kept so strategies can inspect vendor OEM slots
    #: (e.g. ``actions.get("Oem", {}).get("#LogServices.Dump")``) without
    #: reaching for ``get_raw``.
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")

    def oem_action(self, name: str) -> Optional[ActionTarget]:
        """
        Look up a collection-level action by name.

        Real BMCs put "OEM-style" collection actions in one of THREE places
        (all observed in the field):

        1. Directly under ``Actions`` — Inspur cs5280h3 exposes
           ``Actions.#LogService.CollectAllLog`` at the top level even though
           the target URL is nested under ``/Actions/Oem/Public/``.
        2. Directly under ``Actions.Oem`` — ZTE:
           ``Actions.Oem.#LogServices.Dump``.
        3. One level deeper under ``Actions.Oem.<vendor>`` — e.g. hypothetical
           ``Actions.Oem.Public.#LogService.CollectAllLog``.

        This method probes all three, in that order, and returns the first
        match. Returns ``None`` when the name is absent everywhere.
        """
        actions = self.actions or {}

        # 1. Top-level Actions[<name>] (Inspur cs5280h3 layout).
        top = actions.get(name)
        if isinstance(top, dict) and top.get("target"):
            return ActionTarget.model_validate(top)

        oem = actions.get("Oem") or {}

        # 2. Direct child of Oem (ZTE layout).
        direct = oem.get(name)
        if isinstance(direct, dict) and direct.get("target"):
            return ActionTarget.model_validate(direct)

        # 3. Nested under a vendor sub-key (Oem.Public.<name>, etc.).
        for _vendor_key, inner in oem.items():
            if not isinstance(inner, dict):
                continue
            candidate = inner.get(name)
            if isinstance(candidate, dict) and candidate.get("target"):
                return ActionTarget.model_validate(candidate)
        return None


class DiagnosticService(Entity):
    """
    ``/redfish/v1/Managers/{id}/DiagnosticService`` — an OEM Manager
    sub-resource observed on smoothcompute BMCs. Exposes CollectBlackBox /
    ExportBlackBox (and screenshot/video actions) via a standard-shaped
    ``Actions`` block.
    """
    #: ``Actions`` block; access typed entries via :meth:`action`.
    actions: Optional[Dict[str, Any]] = Field(None, alias="Actions")

    def action(self, name: str) -> Optional[ActionTarget]:
        """Return the typed ``ActionTarget`` for ``Actions[<name>]``."""
        raw = (self.actions or {}).get(name)
        if isinstance(raw, dict) and raw.get("target"):
            return ActionTarget.model_validate(raw)
        return None


class ZteDumpProgress(BaseModel):
    """
    ZTE OEM ``.../LogServices/Actions/LogServices.Dump/Progress`` payload.

    Not a Redfish TaskService entry — it's a bespoke progress endpoint
    unique to ZTE. Fields observed in the wild:

    ``State``       — e.g. ``"STATE_COMPLETED"``, ``"STATE_FAILED"``,
                      ``"STATE_RUNNING"``.
    ``Percentage``  — string int (``"-1"`` when idle/failed, ``"100"`` at
                      completion).
    ``TarPath``     — path of the produced bundle on the BMC. When idle
                      the BMC returns ``".tar.gz"`` (empty basename) — an
                      obvious placeholder that callers must treat as "no
                      artifact".
    ``Type``        — collection type, e.g. ``"AllLogs"``.
    ``Message``     — free-form status string, e.g. ``"FAILED"``.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    state: Optional[str] = Field(None, alias="State")
    percentage: Optional[str] = Field(None, alias="Percentage")
    tar_path: Optional[str] = Field(None, alias="TarPath")
    type_: Optional[str] = Field(None, alias="Type")
    message: Optional[str] = Field(None, alias="Message")

    def is_valid_tar_path(self) -> bool:
        """
        True when ``TarPath`` looks like a real produced bundle (not the
        BMC's idle placeholder ``".tar.gz"``).
        """
        tp = (self.tar_path or "").strip()
        return bool(tp) and tp != ".tar.gz"

    def snapshot(self) -> Dict[str, Any]:
        """Serialisable snapshot dict for LogCollectFailedError.progress_history."""
        return {
            "state": self.state or "",
            "percentage": self.percentage,
            "tar_path": self.tar_path,
            "message": self.message,
            "type": self.type_,
        }


class _OemPublicProgress(BaseModel):
    """Inner ``Oem.Public`` object of :class:`LenovoCollectProgress`."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    progress: Optional[int] = Field(None, alias="Progress")
    status: Optional[int] = Field(None, alias="Status")


class _OemLenovoWrapper(BaseModel):
    """The ``Oem`` container as Lenovo returns it: ``{"Public": {...}}``."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    public: Optional[_OemPublicProgress] = Field(None, alias="Public")


class LenovoCollectProgress(BaseModel):
    """
    Lenovo OEM ``.../LogServices/Actions/Oem/Public/CollectProgress`` payload.

    Not a Redfish TaskService entry — GET-only endpoint that returns::

        {"Oem": {"Public": {"Progress": <0..100>, "Status": <int>}}}

    ``Progress`` is an int percentage (jumps quickly to 100 on this BMC's
    firmware — observed on Lenovo servers with an AMI MegaRAC base). Lenovo
    does not appear to expose a distinct terminal state code; the strategy
    treats ``Progress >= 100`` as done and any non-zero ``Status`` as a
    failure signal (Status:0 = OK based on real-BMC observation).
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    oem: Optional[_OemLenovoWrapper] = Field(None, alias="Oem")

    @property
    def progress(self) -> Optional[int]:
        """Convenience: return ``Oem.Public.Progress`` or ``None``."""
        if self.oem and self.oem.public:
            return self.oem.public.progress
        return None

    @property
    def status(self) -> Optional[int]:
        """Convenience: return ``Oem.Public.Status`` or ``None``."""
        if self.oem and self.oem.public:
            return self.oem.public.status
        return None

    def is_done(self) -> bool:
        """True when the collection has finished (progress reached 100)."""
        p = self.progress
        return p is not None and p >= 100

    def snapshot(self) -> Dict[str, Any]:
        """Serialisable snapshot dict for LogCollectFailedError.progress_history."""
        return {"progress": self.progress, "status": self.status}
