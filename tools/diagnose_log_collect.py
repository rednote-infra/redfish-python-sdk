"""
Diagnostic helper: discover where a BMC exposes diagnostic-data collection.

This台 BMC 未在 Manager 侧的 LogService 暴露标准
``#LogService.CollectDiagnosticData``。此脚本遍历 Manager 侧和 System 侧的
所有 LogService，打印每个服务原始 JSON 的 Actions / Oem 块，以及集合本身的
Actions / Oem，帮助定位真正的采集入口（可能是非标准 action 名、OEM action、
或 System 侧的服务）。

用法：
    export BMC_IP=...
    export BMC_USER=...
    export BMC_PASSWORD=...
    python tools/diagnose_log_collect.py

把完整输出贴回来即可。
"""
from __future__ import annotations

import json
import os

from redfish_sdk import RedfishClient


def _dump(client: RedfishClient, odata_id: str, indent: str = "  ") -> None:
    try:
        raw = client._http_client.get_raw(odata_id)
    except Exception as exc:  # noqa: BLE001 — diagnostic best-effort
        print(f"{indent}!! GET {odata_id} failed: {exc}")
        return

    actions = raw.get("Actions")
    oem = raw.get("Oem")
    print(f"{indent}@odata.id : {raw.get('@odata.id', odata_id)}")
    print(f"{indent}Id        : {raw.get('Id')}")
    print(f"{indent}Name      : {raw.get('Name')}")
    print(f"{indent}Actions   : {json.dumps(actions, ensure_ascii=False)}")
    if oem:
        print(f"{indent}Oem       : {json.dumps(oem, ensure_ascii=False)}")
    # Surface any key that looks collection-of-diagnostics related.
    for key in raw:
        if any(w in key.lower() for w in ("diag", "dump", "collect", "sds")):
            print(f"{indent}~ hint key: {key} = "
                  f"{json.dumps(raw[key], ensure_ascii=False)[:200]}")


def _walk_log_services(client: RedfishClient, collection_odata_id: str) -> None:
    print(f"\n=== LogServices collection: {collection_odata_id} ===")
    try:
        col = client._http_client.get_raw(collection_odata_id)
    except Exception as exc:  # noqa: BLE001
        print(f"  !! GET collection failed: {exc}")
        return

    # Some BMCs expose Actions/Oem on the collection itself.
    if col.get("Actions"):
        print(f"  collection Actions: "
              f"{json.dumps(col['Actions'], ensure_ascii=False)}")
    if col.get("Oem"):
        print(f"  collection Oem: "
              f"{json.dumps(col['Oem'], ensure_ascii=False)}")

    for member in col.get("Members", []):
        mid = member.get("@odata.id")
        if not mid:
            continue
        print(f"\n  --- LogService member: {mid} ---")
        _dump(client, mid, indent="    ")


def main() -> None:
    client = RedfishClient(
        host=os.environ["BMC_IP"],
        username=os.environ["BMC_USER"],
        password=os.environ["BMC_PASSWORD"],
        verify_ssl=False,
    )
    try:
        root = client._http_client.get_raw("/redfish/v1/")

        # Manager side
        mgr_col = root.get("Managers", {}).get("@odata.id")
        if mgr_col:
            managers = client._http_client.get_raw(mgr_col).get("Members", [])
            for m in managers:
                mid = m.get("@odata.id")
                mgr = client._http_client.get_raw(mid)
                ls = mgr.get("LogServices", {}).get("@odata.id")
                print(f"\n########## MANAGER {mid} ##########")
                if mgr.get("Actions"):
                    print(f"  Manager Actions: "
                          f"{json.dumps(mgr['Actions'], ensure_ascii=False)}")
                if mgr.get("Oem"):
                    print(f"  Manager Oem keys: {list(mgr['Oem'].keys())}")
                if ls:
                    _walk_log_services(client, ls)

        # System side
        sys_col = root.get("Systems", {}).get("@odata.id")
        if sys_col:
            systems = client._http_client.get_raw(sys_col).get("Members", [])
            for s in systems:
                sid = s.get("@odata.id")
                sysres = client._http_client.get_raw(sid)
                ls = sysres.get("LogServices", {}).get("@odata.id")
                print(f"\n########## SYSTEM {sid} ##########")
                if ls:
                    _walk_log_services(client, ls)
    finally:
        client.close()


if __name__ == "__main__":
    main()
