"""
Mock tests for the Firewall (Enginetech OEM extension) APIs.

Covers:
  - Model parsing of the Enginetech Firewall / IPRules / PortRules /
    FirewallConfig resources.
  - Backwards compatibility: the pre-1.3.0 ``FirewallRules`` model still
    absorbs an Enginetech payload instead of raising.
  - The multi-level firewall URI discovery chain.
  - The new ``Client`` getters.

These tests never hit a real BMC; HTTP calls are stubbed via monkeypatch on
``RedfishClient._http_client``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Type

import pytest

from redfish_sdk import (
    Firewall,
    FirewallConfigEntry,
    FirewallIpRule,
    FirewallPortRule,
    FirewallRules,
    RedfishClient,
    RedfishValidationError,
)
from redfish_sdk.exceptions import RedfishNotFoundError

MOCK_HOST = os.environ.get("BMC_IP", "mock-bmc-host")
MOCK_USER = os.environ.get("BMC_USER", "mock-user")
MOCK_PASSWORD = os.environ.get("BMC_PASSWORD", "mock-password")

MANAGER_URI = "/redfish/v1/Managers/Self"
FIREWALL_URI = "/redfish/v1/Managers/Self/Oem/Firewall"
IP_RULES_URI = "/redfish/v1/Managers/Self/Oem/Firewall/IPRules"
PORT_RULES_URI = "/redfish/v1/Managers/Self/Oem/Firewall/PortRules"
CONFIG_URI = "/redfish/v1/Managers/Self/Oem/Firewall/FirewallConfig"

# ---------------------------------------------------------------------------
# Payloads captured from an Enginetech BMC
# ---------------------------------------------------------------------------

FIREWALL_ROOT = {
    "@odata.context": "/redfish/v1/$metadata",
    "@odata.etag": '"1791600077"',
    "@odata.id": FIREWALL_URI,
    "@odata.type": "#AMIFirewall.v1_0_0.AMIFirewall",
    "Description": "Firewall configuration and rules for this system",
    "FirewallConfig": {"@odata.id": CONFIG_URI},
    "IPRules": {"@odata.id": IP_RULES_URI},
    "Name": "Firewall",
    "PortRules": {"@odata.id": PORT_RULES_URI},
}

IP_RULES_COLLECTION = {
    "@odata.id": IP_RULES_URI,
    "@odata.type": "#AMIFirewall.v1_0_0.AMIFirewall",
    "Description": "Collection of firewall IP rules",
    "Members": [{"@odata.id": f"{IP_RULES_URI}/0"}],
    "Members@odata.count": 1,
    "Name": "IPRules",
}

IP_RULE_0 = {
    "@odata.id": f"{IP_RULES_URI}/0",
    "@odata.type": "#AMIFirewall.v1_0_0.AMIFirewall",
    "Description": "Firewall IP rule entry",
    "IPAddress1": "10.10.10.1",
    "IPAddress2": "10.10.10.2",
    "IPVersion": "IPv4",
    "Id": "0",
    "Name": "IPRule 0",
    "Position": 0,
    "State": "BLOCK",
    "Timeout": {"StartTime": "2026-08-27 10:00:00", "StopTime": "2026-08-27 12:00:00"},
    "Type": "IPv4+StateTimeout",
}

PORT_RULES_COLLECTION = {
    "@odata.id": PORT_RULES_URI,
    "@odata.type": "#AMIFirewall.v1_0_0.AMIFirewall",
    "Description": "Collection of firewall Port rules",
    "Members": [{"@odata.id": f"{PORT_RULES_URI}/{i}"} for i in range(4)],
    "Members@odata.count": 4,
    "Name": "PortRules",
}

PORT_RULE_1 = {
    "@odata.id": f"{PORT_RULES_URI}/1",
    "@odata.type": "#AMIFirewall.v1_0_0.AMIFirewall",
    "Description": "Firewall Port rule entry",
    "IPVersion": "IPv4",
    "Id": "1",
    "Name": "PortRule 1",
    "Port1": 6087,
    "Port2": 6088,
    "Position": 3,
    "Protocol": "TCP",
    "State": "BLOCK",
    "Timeout": {"StartTime": "2026-08-28 10:00:00", "StopTime": "2026-08-28 18:00:00"},
    "Type": "PortRangeTimeout",
}

CONFIG_COLLECTION = {
    "@odata.id": CONFIG_URI,
    "@odata.type": "#AMIFirewall.v1_0_0.AMIFirewall",
    "Description": "Firewall block-all configuration entries",
    "Members": [{"@odata.id": f"{CONFIG_URI}/0"}, {"@odata.id": f"{CONFIG_URI}/1"}],
    "Members@odata.count": 2,
    "Name": "FirewallConfig",
}

# Note the lower-case "id" / snake-case "timeout_enabled" — every sibling
# resource uses "Id" instead.
CONFIG_ENTRY_0 = {
    "@odata.id": f"{CONFIG_URI}/0",
    "@odata.type": "#AMIFirewall.v1_0_0.AMIFirewall",
    "Description": "Firewall block-all configuration entry",
    "IPVersion": "IPv4",
    "Name": "FirewallConfig 0",
    "Timeout": {"StartTime": "2026-08-05 00:00:00", "StopTime": "2026-08-05 23:59:00"},
    "id": 0,
    "timeout_enabled": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> RedfishClient:
    return RedfishClient(host=MOCK_HOST, username=MOCK_USER, password=MOCK_PASSWORD)


def _manager_raw(oem: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "@odata.id": MANAGER_URI,
        "Id": "Self",
        "Name": "Manager",
        "Oem": oem,
    }


def _install_routes(monkeypatch, client: RedfishClient, routes: Dict[str, Any]) -> None:
    """Stub ``http_client.get`` / ``get_raw`` with a path -> raw payload map."""

    def fake_get(path: str, model_class: Type[Any]):
        if path not in routes:
            raise AssertionError(f"unexpected GET {path}")
        return model_class.model_validate(routes[path])

    def fake_get_raw(path: str):
        if path not in routes:
            raise AssertionError(f"unexpected GET (raw) {path}")
        return routes[path]

    monkeypatch.setattr(client._http_client, "get", fake_get)
    monkeypatch.setattr(client._http_client, "get_raw", fake_get_raw)
    monkeypatch.setattr(
        client, "_get_managers_collection_odata_id", lambda: "/redfish/v1/Managers"
    )


# ---------------------------------------------------------------------------
# Model parsing
# ---------------------------------------------------------------------------


class TestFirewallModelParsing:
    def test_firewall_root_exposes_three_collection_links(self):
        fw = Firewall.model_validate(FIREWALL_ROOT)

        assert fw.odata_id == FIREWALL_URI
        assert fw.name == "Firewall"
        assert fw.firewall_config is not None
        assert fw.firewall_config.odata_id == CONFIG_URI
        assert fw.ip_rules is not None
        assert fw.ip_rules.odata_id == IP_RULES_URI
        assert fw.port_rules is not None
        assert fw.port_rules.odata_id == PORT_RULES_URI
        # Enginetech root is a navigation container, not a collection.
        assert fw.members is None
        assert fw.members_count is None

    def test_ip_rule(self):
        rule = FirewallIpRule.model_validate(IP_RULE_0)

        assert rule.id == "0"
        assert rule.ip_version == "IPv4"
        assert rule.ip_address1 == "10.10.10.1"
        assert rule.ip_address2 == "10.10.10.2"
        assert rule.position == 0
        assert rule.state == "BLOCK"
        assert rule.type == "IPv4+StateTimeout"
        assert rule.timeout is not None
        assert rule.timeout.start_time == "2026-08-27 10:00:00"
        assert rule.timeout.stop_time == "2026-08-27 12:00:00"
        # Port fields simply stay unset on an IP rule.
        assert rule.port1 is None

    def test_port_rule(self):
        rule = FirewallPortRule.model_validate(PORT_RULE_1)

        assert rule.id == "1"
        assert rule.port1 == 6087
        assert rule.port2 == 6088
        assert rule.protocol == "TCP"
        assert rule.position == 3
        assert rule.ip_version == "IPv4"
        assert rule.state == "BLOCK"
        assert rule.type == "PortRangeTimeout"
        assert rule.timeout.start_time == "2026-08-28 10:00:00"
        assert rule.timeout.stop_time == "2026-08-28 18:00:00"

    def test_config_entry_normalizes_lower_case_id(self):
        entry = FirewallConfigEntry.model_validate(CONFIG_ENTRY_0)

        # "id" (lower case) must land on Entity.id just like "Id" does.
        assert entry.id == 0
        assert entry.timeout_enabled is True
        assert entry.ip_version == "IPv4"
        assert entry.timeout.stop_time == "2026-08-05 23:59:00"

    def test_compat_legacy_firewall_rules_absorbs_enginetech_payload(self):
        """Pre-1.3.0 callers must not break on the Enginetech shape."""
        legacy = FirewallRules.model_validate(FIREWALL_ROOT)

        assert legacy.odata_id == FIREWALL_URI
        assert legacy.members is None
        # Links live in model_extra because FirewallRules has no typed fields
        # for them — no validation error, no data loss.
        assert (legacy.model_extra or {}).get("IPRules") is not None

    def test_compat_legacy_shape_still_parses(self):
        legacy = FirewallRules.model_validate(
            {
                "@odata.id": "/redfish/v1/Managers/1/FirewallRules",
                "Members": [{"@odata.id": "/redfish/v1/Managers/1/FirewallRules/0"}],
                "Members@odata.count": 1,
            }
        )
        assert legacy.members_count == 1
        assert legacy.members[0].odata_id == "/redfish/v1/Managers/1/FirewallRules/0"


# ---------------------------------------------------------------------------
# URI discovery
# ---------------------------------------------------------------------------


class TestFirewallDiscovery:
    def test_prefers_oem_firewall(self, monkeypatch):
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {MANAGER_URI: _manager_raw({"Firewall": {"@odata.id": FIREWALL_URI}})},
        )
        assert client._managers._get_firewall_link("Self") == FIREWALL_URI

    def test_discovers_ami_oem_firewall(self, monkeypatch):
        """AMI MegaRAC publishes the container under Oem.Ami, not FirewallRules."""
        ami_uri = "/redfish/v1/Managers/Self/Oem/Ami/Firewall"
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw(
                    {"Ami": {"Firewall": {"@odata.id": ami_uri}}}
                )
            },
        )
        assert client._managers._get_firewall_link("Self") == ami_uri

    def test_discovers_ami_firewallrules_key(self, monkeypatch):
        """Some AMI SKUs keep the legacy key under Oem.Ami."""
        ami_rules_uri = "/redfish/v1/Managers/Self/Oem/Ami/FirewallRules"
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw(
                    {"Ami": {"FirewallRules": {"@odata.id": ami_rules_uri}}}
                )
            },
        )
        assert client._managers._get_firewall_link("Self") == ami_rules_uri

    def test_probes_ami_path_when_oem_key_has_no_link(self, monkeypatch):
        """An Ami block without a link still gets the conventional path probed."""
        ami_uri = "/redfish/v1/Managers/Self/Oem/Ami/Firewall"
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw({"Ami": {}}),
                ami_uri: FIREWALL_ROOT,
            },
        )
        assert client._managers._get_firewall_link("Self") == ami_uri

    def test_falls_back_to_public_firewall_rules(self, monkeypatch):
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw(
                    {"Public": {"FirewallRules": {"@odata.id": "/Managers/1/FirewallRules"}}}
                )
            },
        )
        assert client._managers._get_firewall_link("Self") == "/Managers/1/FirewallRules"

    def test_falls_back_to_public_firewall(self, monkeypatch):
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw(
                    {"Enginetech": {"Firewall": {"@odata.id": FIREWALL_URI}}}
                )
            },
        )
        assert client._managers._get_firewall_link("Self") == FIREWALL_URI

    def test_falls_back_to_security_service_links(self, monkeypatch):
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw(
                    {
                        "Public": {
                            "SecurityService": {
                                "@odata.id": "/redfish/v1/Managers/1/SecurityService"
                            }
                        }
                    }
                ),
                "/redfish/v1/Managers/1/SecurityService": {
                    "@odata.id": "/redfish/v1/Managers/1/SecurityService",
                    "Links": {
                        "FirewallRules": {
                            "@odata.id": "/redfish/v1/Managers/1/SecurityService/FirewallRules"
                        }
                    },
                },
            },
        )
        assert (
            client._managers._get_firewall_link("Self")
            == "/redfish/v1/Managers/1/SecurityService/FirewallRules"
        )

    def test_raises_when_no_firewall_exposed(self, monkeypatch):
        client = _make_client()
        _install_routes(monkeypatch, client, {MANAGER_URI: _manager_raw({})})

        with pytest.raises(RedfishNotFoundError):
            client._managers._get_firewall_link("Self")


# ---------------------------------------------------------------------------
# Client getters
# ---------------------------------------------------------------------------


class TestFirewallClientGetters:
    def test_get_firewall(self, monkeypatch):
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw({"Firewall": {"@odata.id": FIREWALL_URI}}),
                FIREWALL_URI: FIREWALL_ROOT,
            },
        )
        fw = client.get_firewall("Self")
        assert isinstance(fw, Firewall)
        assert fw.ip_rules.odata_id == IP_RULES_URI

    def test_get_firewall_ip_rules_expands_members(self, monkeypatch):
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw({"Firewall": {"@odata.id": FIREWALL_URI}}),
                FIREWALL_URI: FIREWALL_ROOT,
                IP_RULES_URI: IP_RULES_COLLECTION,
                f"{IP_RULES_URI}/0": IP_RULE_0,
            },
        )
        rules = client.get_firewall_ip_rules("Self")

        assert len(rules) == 1
        assert isinstance(rules[0], FirewallIpRule)
        assert rules[0].ip_address1 == "10.10.10.1"
        assert rules[0].state == "BLOCK"

    def test_get_firewall_port_rules_expands_members(self, monkeypatch):
        client = _make_client()
        routes = {
            MANAGER_URI: _manager_raw({"Firewall": {"@odata.id": FIREWALL_URI}}),
            FIREWALL_URI: FIREWALL_ROOT,
            PORT_RULES_URI: {
                **PORT_RULES_COLLECTION,
                "Members": [{"@odata.id": f"{PORT_RULES_URI}/1"}],
                "Members@odata.count": 1,
            },
            f"{PORT_RULES_URI}/1": PORT_RULE_1,
        }
        _install_routes(monkeypatch, client, routes)

        rules = client.get_firewall_port_rules("Self")
        assert len(rules) == 1
        assert rules[0].port1 == 6087
        assert rules[0].protocol == "TCP"

    def test_get_firewall_config_entries_expands_members(self, monkeypatch):
        client = _make_client()
        routes = {
            MANAGER_URI: _manager_raw({"Firewall": {"@odata.id": FIREWALL_URI}}),
            FIREWALL_URI: FIREWALL_ROOT,
            CONFIG_URI: {
                **CONFIG_COLLECTION,
                "Members": [{"@odata.id": f"{CONFIG_URI}/0"}],
                "Members@odata.count": 1,
            },
            f"{CONFIG_URI}/0": CONFIG_ENTRY_0,
        }
        _install_routes(monkeypatch, client, routes)

        entries = client.get_firewall_config_entries("Self")
        assert len(entries) == 1
        assert entries[0].id == 0
        assert entries[0].timeout_enabled is True

    def test_get_firewall_rule_collection_returns_count(self, monkeypatch):
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw({"Firewall": {"@odata.id": FIREWALL_URI}}),
                FIREWALL_URI: FIREWALL_ROOT,
                PORT_RULES_URI: PORT_RULES_COLLECTION,
            },
        )
        coll = client.get_firewall_rule_collection("Self", kind="PortRules")

        assert coll.members_count == 4
        assert len(coll.members) == 4

    def test_unknown_collection_kind_raises(self, monkeypatch):
        client = _make_client()
        _install_routes(monkeypatch, client, {})

        with pytest.raises(RedfishValidationError):
            client.get_firewall_rule_collection("Self", kind="Nope")

    def test_missing_sub_collection_raises_not_found(self, monkeypatch):
        client = _make_client()
        # Root without a PortRules link.
        root = {k: v for k, v in FIREWALL_ROOT.items() if k != "PortRules"}
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw({"Firewall": {"@odata.id": FIREWALL_URI}}),
                FIREWALL_URI: root,
            },
        )
        with pytest.raises(RedfishNotFoundError):
            client.get_firewall_port_rules("Self")

    def test_deprecated_get_firewall_rules_still_works(self, monkeypatch):
        client = _make_client()
        _install_routes(
            monkeypatch,
            client,
            {
                MANAGER_URI: _manager_raw({"Firewall": {"@odata.id": FIREWALL_URI}}),
                FIREWALL_URI: FIREWALL_ROOT,
            },
        )
        legacy = client.get_firewall_rules("Self")

        assert isinstance(legacy, FirewallRules)
        assert legacy.odata_id == FIREWALL_URI
