# redfish-python-sdk

> A lightweight Python SDK for managing server BMCs (Baseboard Management Controllers) via the [DMTF Redfish](https://www.dmtf.org/standards/redfish) protocol. Covers system inventory, hardware inspection, power control, boot management, event subscriptions, and more.

[![PyPI version](https://img.shields.io/pypi/v/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![License](https://img.shields.io/pypi/l/redfish-python-sdk)](https://github.com/rednote-infra/redfish-python-sdk/blob/main/LICENSE)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/redfish-python-sdk?period=total&units=INTERNATIONAL_SYSTEM&left_color=GRAY&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/redfish-python-sdk)

[English](README.md) | [中文](README_zh.md)

## Features

- **Hardware inventory** — query CPU, memory, drives, GPU, NIC, PCIe, PSUs, and cooling resources
- **Power & boot management** — power on/off, restart, and PXE/disk/BIOS setup boot overrides
- **BIOS configuration** — pending settings, Attribute Registry discovery, static attribute preflight, and supported apply-time schedules
- **Multi-vendor support** — standard Redfish resources and targeted OEM adapters; availability depends on BMC firmware
- **Extensible OEM providers** — installable, client-scoped providers for firmware updates, diagnostic log collection, and OEM field extraction
- **Pydantic v2 models** — typed resource getters provide validation and IDE autocompletion
- **Sync & async APIs** — `AsyncRedfishClient` runs Requests in worker threads without adding another HTTP dependency
- **Authentication** — Basic and Redfish session authentication, safe-read session refresh, and managed session cleanup
- **Generic HTTP API** — GET/HEAD/POST/PUT/PATCH/DELETE with query parameters, conditional headers, per-request timeouts, and response metadata
- **Configurable transport** — caller-owned Requests sessions, proxies, and private CA bundles
- **Service discovery** — configurable service roots and standalone, bounded IPv4/IPv6 SSDP discovery without authentication
- **Resource indexing** — bounded discovery and exact filtering by `@odata.type` and properties, with partial-failure diagnostics
- **Change-set planning** — stage changes, preview redacted diffs, dry-run, check ETags, and submit in order; no atomicity or rollback guarantee
- **Structured errors** — typed HTTP/Redfish details, password-change-required detection, and redacted diagnostic displays
- **Context manager** — use `with` for automatic client cleanup
- **Minimal dependencies** — direct runtime dependencies on `requests` and `pydantic`

## Installation

Requires Python 3.9 or later; CI covers Python 3.9–3.13. This README describes the current `main` branch; released packages may differ. Install from GitHub for current source behavior.

```bash
# Install from PyPI
pip install redfish-python-sdk

# Or install the current main branch from GitHub
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@main
```

To pin a release, use `redfish-python-sdk==VERSION` for PyPI or replace `@main` with `@TAG` in the Git URL.

## Quick Start

Set `BMC_IP`, `BMC_USER`, and `BMC_PASSWORD` in your environment before running this read-only example. Keep credentials out of source code.

```python
import os

from redfish_sdk import RedfishClient

with RedfishClient(
    host=os.environ["BMC_IP"],
    username=os.environ["BMC_USER"],
    password=os.environ["BMC_PASSWORD"],
    verify_ssl=True,
) as client:
    # Get system information.
    system = client.get_system()
    print(f"Server: {system.manufacturer} {system.model}")
    print(f"SN:     {system.serial_number}")
    print(f"Power:  {system.power_state}")

    # Get CPU information.
    for cpu in client.get_processors():
        print(f"CPU: {cpu.model}, {cpu.total_cores} cores / {cpu.total_threads} threads")

    # Get memory information; missing capacity stays unknown.
    for mem in client.get_memory():
        capacity = "unknown" if mem.capacity_mib is None else f"{mem.capacity_mib / 1024:.1f} GiB"
        print(f"DIMM: {mem.manufacturer} {capacity}")

    # Get drive information.
    for drive in client.get_drives():
        capacity = "unknown" if drive.capacity_bytes is None else f"{drive.capacity_bytes / 1e12:.1f} TB"
        print(f"Drive: {drive.model} {capacity}")
```

The example enables TLS certificate verification. For a BMC using a private or self-signed CA, supply `ca_bundle="/path/to/bmc-ca.pem"`. For a trusted test environment, explicitly setting `verify_ssl=False` disables verification.

For BMCs exposing multiple systems or chassis, pass `system_id` or `chassis_id` to the corresponding getters.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the [BSD 3-Clause License](LICENSE).
