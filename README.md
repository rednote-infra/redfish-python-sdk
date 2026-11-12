# redfish-python-sdk

> A lightweight Python SDK for managing server BMCs (Baseboard Management Controllers) via the [DMTF Redfish](https://www.dmtf.org/standards/redfish) protocol. Covers system inventory, hardware inspection, power control, boot management, event subscriptions, and more.

[![PyPI version](https://img.shields.io/pypi/v/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![License](https://img.shields.io/pypi/l/redfish-python-sdk)](https://github.com/rednote-infra/redfish-python-sdk/blob/main/LICENSE)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/redfish-python-sdk?period=total&units=INTERNATIONAL_SYSTEM&left_color=GRAY&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/redfish-python-sdk)

[English](README.md) | [中文](README_zh.md)

## Features

- **Multi-vendor hardware inventory** — inspect CPU, memory, GPU, storage, networking, power, and cooling through one SDK
- **Remote power & boot control** — power servers on/off, restart them, and select PXE, disk, or BIOS setup boot
- **BIOS configuration** — check attribute values before updating pending settings and schedule when changes take effect
- **Firmware updates & diagnostics** — update firmware and collect/download diagnostic bundles for troubleshooting
- **Find resources quickly** — discover standard and OEM resources by type and properties without hardcoding collection paths
- **Preview changes before applying** — inspect configuration diffs, validate and dry-run changes, then submit them in order
- **Async automation** — coordinate operations across multiple BMCs with `AsyncRedfishClient`

## Installation

```bash
# Install from PyPI
pip install redfish-python-sdk

# Or install from GitHub
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git

# Install a specific version
pip install redfish-python-sdk==1.2.3
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@v1.2.3
```

## Quick Start

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

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the [BSD 3-Clause License](LICENSE).
