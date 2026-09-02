"""
Pre-flight check for a BMC before running diagnostic-log collection.

Run this first on any new BMC to quickly tell apart the common failure modes
we've hit in the field (see PR #10 troubleshooting notes):

    - Network unreachable / port not listening   -> environment / wrong IP
    - HTTPS reachable but very slow / 5xx        -> BMC firmware overload
    - Redfish LogServices missing or 501         -> BMC LogServices subsystem
                                                    broken (SDK can't help)
    - LogServices OK but no CollectDiagnosticData action -> vendor uses an
      OEM scheme; the SDK strategies pick it up automatically

Usage:
    export BMC_IP=...
    export BMC_USER=...
    export BMC_PASSWORD=...
    python tools/preflight_check.py

The script exits 0 when the BMC looks collection-ready, non-zero otherwise,
so it can be used as a gate in CI/automation.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from urllib.parse import urlsplit

from redfish_sdk import RedfishClient
from redfish_sdk.exceptions import (
    RedfishConnectionError,
    RedfishException,
    RedfishTimeoutError,
)


HOST = os.environ.get("BMC_IP")
USER = os.environ.get("BMC_USER")
PASS = os.environ.get("BMC_PASSWORD")


def _die(code: int, why: str) -> None:
    print(f"\nFAIL: {why}")
    sys.exit(code)


def _check_tcp(host: str, port: int, timeout: float = 3.0) -> str:
    """Return 'open' / 'refused' / 'filtered' / 'error:<detail>'."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return "open"
    except ConnectionRefusedError:
        return "refused"
    except socket.timeout:
        return "filtered"
    except OSError as exc:
        return f"error:{exc}"


def main() -> None:
    if not (HOST and USER and PASS):
        _die(2, "Set BMC_IP / BMC_USER / BMC_PASSWORD env vars first.")

    print(f"=== Pre-flight check: {HOST} ===")

    # --- 1) Cheap TCP probe on 443 -------------------------------------
    tcp = _check_tcp(HOST, 443)
    print(f"[1] TCP 443              : {tcp}")
    if tcp == "refused":
        _die(3,
             f"443/tcp refused. Likely: (a) {HOST} is a host-OS IP, not the "
             f"BMC management IP; (b) BMC Redfish/HTTPS is disabled. Verify "
             f"the IP is the BMC and Redfish is on.")
    if tcp == "filtered":
        _die(3,
             f"443/tcp did not respond within 3s. Likely: firewall / VPN "
             f"path drop, or BMC unreachable from this host.")
    if tcp.startswith("error"):
        _die(3, f"Cannot open TCP to {HOST}:443 ({tcp}).")

    # --- 2) Redfish root, once, timed ----------------------------------
    client = RedfishClient(
        host=HOST, username=USER, password=PASS,
        verify_ssl=False, connect_timeout=5, read_timeout=15,
    )
    try:
        t0 = time.time()
        try:
            root = client._http_client.get_raw("/redfish/v1/")
        except RedfishTimeoutError:
            _die(4,
                 f"BMC accepted TCP but did not respond to GET /redfish/v1/ "
                 f"within 15s. It's overloaded/half-hung. Retry with:\n"
                 f"  RedfishClient(host=..., read_timeout=60, retry_5xx=3, "
                 f"retry_on_read_timeout=True)")
        except RedfishConnectionError as exc:
            _die(4, f"HTTPS to {HOST} failed: {exc}")
        except RedfishException as exc:
            _die(4, f"GET /redfish/v1/ returned HTTP {exc.status_code}: {exc}")
        rt = time.time() - t0
        print(f"[2] GET /redfish/v1/     : {rt*1000:.0f} ms  "
              f"vendor={root.get('Vendor') or '(unset)'}  "
              f"oem={list((root.get('Oem') or {}).keys()) or '(none)'}")
        if rt > 5:
            print("    WARNING: >5s response — BMC is slow; consider "
                  "read_timeout=60 + retry_5xx=3 for collection.")

        # --- 3) Managers collection -----------------------------------
        managers_link = (root.get("Managers") or {}).get("@odata.id")
        if not managers_link:
            _die(5, "Root service has no Managers link — non-standard BMC.")
        mgrs = client._http_client.get_raw(managers_link)
        member_ids = [m.get("@odata.id") for m in mgrs.get("Members", [])]
        print(f"[3] Managers members     : {member_ids}")
        if not member_ids:
            _die(5, "Managers collection is empty.")

        # --- 4) LogServices on the (single/first) Manager -------------
        mgr_url = member_ids[0]
        try:
            mgr = client._http_client.get_raw(mgr_url)
        except RedfishException as exc:
            _die(6, f"GET {mgr_url} failed: {exc}")
        ls_link = (mgr.get("LogServices") or {}).get("@odata.id")
        if not ls_link:
            print(f"[4] Manager LogServices  : (no link) — will fall back to "
                  "System side.")
        else:
            try:
                ls = client._http_client.get_raw(ls_link)
                svcs = [x.get("@odata.id") for x in ls.get("Members", [])]
                col_actions = list((ls.get("Actions") or {}).keys())
                oem_actions = list(((ls.get("Actions") or {}).get("Oem") or {}).keys())
                print(f"[4] Manager LogServices  : {len(svcs)} member(s), "
                      f"collection Actions={col_actions or '(none)'}, "
                      f"Oem={oem_actions or '(none)'}")
                # Look for a per-service CollectDiagnosticData action.
                have_std = False
                for s in svcs:
                    try:
                        sr = client._http_client.get_raw(s)
                        if (sr.get("Actions") or {}).get(
                            "#LogService.CollectDiagnosticData"
                        ):
                            have_std = True
                            print(f"    [ok] {s} exposes standard "
                                  "CollectDiagnosticData")
                    except RedfishException as exc:
                        print(f"    [warn] {s} -> HTTP {exc.status_code}")
                # OEM style collection actions (Inspur/ZTE families) live on
                # the collection itself.
                if oem_actions:
                    print(f"    [ok] Collection-level OEM actions available: "
                          f"{oem_actions}")
                if not (have_std or oem_actions):
                    _die(7,
                         "No CollectDiagnosticData action found on any "
                         "LogService and no OEM collection action either. "
                         "This BMC firmware does not expose a diagnostic "
                         "collection entry point.")
            except RedfishException as exc:
                if exc.status_code == 501:
                    _die(7,
                         f"GET {ls_link} returned HTTP 501 (Not Implemented). "
                         f"This BMC's LogServices subsystem is not functional "
                         f"— firmware issue, cannot be fixed from the SDK.")
                _die(6, f"GET {ls_link} failed: {exc}")

        print("\nOK: BMC looks collection-ready. Recommended run:")
        print("    client = RedfishClient(host=BMC_IP, username=..., "
              "password=..., read_timeout=60,")
        print("                           retry_5xx=2, "
              "retry_on_read_timeout=True)")
        print("    client.collect_and_download_diagnostic_data(\"./bundle/\","
              " max_retries=1)")
        sys.exit(0)
    finally:
        client.close()


if __name__ == "__main__":
    main()
