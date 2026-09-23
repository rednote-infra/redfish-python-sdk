# redfish-python-sdk
**redfish-python-sdk** is a typed, high-level Python SDK for managing
multi-vendor BMCs and bare-metal servers through the DMTF Redfish API.

[![PyPI version](https://img.shields.io/pypi/v/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![License](https://img.shields.io/pypi/l/redfish-python-sdk)](https://github.com/rednote-infra/redfish-python-sdk/blob/main/LICENSE)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/redfish-python-sdk?period=total&units=INTERNATIONAL_SYSTEM&left_color=GRAY&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/redfish-python-sdk)

[English](README.md) | [中文](README_zh.md)

> A lightweight Python SDK for managing server BMCs (Baseboard Management Controllers) via the [DMTF Redfish](https://www.dmtf.org/standards/redfish) protocol. Covers system inventory, hardware inspection, power control, boot management, event subscriptions, and more.

## Features

- **Comprehensive hardware queries** — CPU, memory, drives, GPU, NIC, PCIe, PSU, fans — one line of code each
- **Power & boot management** — power on/off, restart, PXE/HDD/BIOS boot source switching
- **Multi-vendor compatible** — auto-adapts to OEM extensions from Huawei, xFusion, Lenovo, HPE, Dell, and others
- **Pydantic v2 models** — all return values are strongly-typed objects with full IDE autocompletion
- **Context manager** — `with` statement support for automatic connection cleanup
- **Minimal dependencies** — only `requests`, `pydantic`, and `urllib3`

## Requirements

- Python >= 3.9
- A network-reachable Redfish-compliant BMC endpoint

## Installation

```bash
# Install from PyPI
pip install redfish-python-sdk

# Or install from GitHub
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git

# Install a specific version
pip install redfish-python-sdk==1.2.3
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@v1.2.3

# In requirements.txt
# redfish-python-sdk>=1.2.3
```

## Quick Start

> **Credential management**: All BMC credentials should be injected via environment variables. **Never** hardcode them in your source code.
> Before running examples or tests, set `export BMC_IP=...`, `export BMC_USER=...`, `export BMC_PASSWORD=...`.

```python
import os
from redfish_sdk import RedfishClient

# Connect to BMC (credentials from environment variables)
client = RedfishClient(
    host=os.environ["BMC_IP"],
    username=os.environ["BMC_USER"],
    password=os.environ["BMC_PASSWORD"],
)

# Get system info
system = client.systems.get()
print(f"Server: {system.manufacturer} {system.model}")
print(f"SN:     {system.serial_number}")
print(f"Power:  {system.power_state}")

# Get CPU info
for cpu in client.get_processors():
    print(f"CPU: {cpu.model}, {cpu.total_cores} cores / {cpu.total_threads} threads")

# Get memory info
for mem in client.get_memory():
    print(f"DIMM: {mem.manufacturer} {(mem.capacity_mib or 0) // 1024} GB")

# Get drive info
for drive in client.get_drives():
    print(f"Drive: {drive.model} {(drive.capacity_bytes or 0) / 1e12:.1f} TB")

# Don't forget to close
client.close()
```

## Manager protocol and OEM fallbacks

Use DMTF-standard fields first. OEM helpers are optional compatibility
fallbacks: a missing OEM endpoint is not a Redfish compliance failure. The SDK
discovers OEM links from `Oem` rather than constructing vendor URIs.

| Use case | Standard path / SDK API | Optional OEM fallback |
| --- | --- | --- |
| DNS | `EthernetInterface.NameServers`, `ManagerNetworkProtocol.HostName` | `get_dns_service()` |
| NTP | `ManagerNetworkProtocol.NTP` | `get_ntp_service()` |
| SNMP | `ManagerNetworkProtocol.SNMP` | `get_snmp_service()` |
| VNC/RFB | `ManagerNetworkProtocol.RFB` | `get_vnc_service()` |
| HTTPS certificates | `get_https_certificates()` follows `ManagerNetworkProtocol.HTTPS.Certificates` | `get_https_cert()` via `SecurityService.Links.HttpsCert` |
| Console availability | `Manager.GraphicalConsole` | `get_kvm_service()` |
| Syslog, LLDP, firewall rules | No generic Manager configuration resource | `get_syslog_service()`, `get_lldp_service()`, `get_firewall_rules()` |

For a standards-compliant BMC, use the standard path when available, then
attempt the documented OEM helper only if the vendor contract requires it.

## Testing

```bash
# Run unit tests (no BMC or env vars required)
pytest tests/test_models_mock.py tests/test_client_mock.py -v

# Run offline tests (using pre-collected JSON data)
export REDFISH_JSON_DIR="./testdata"
pytest tests/test_offline_json.py -v

# Run integration tests (requires a real BMC)
export BMC_IP="<your-bmc-ip>"
export BMC_USER="<your-bmc-user>"
export BMC_PASSWORD="<your-bmc-password>"
pytest tests/test_real_bmc.py -v
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the [BSD 3-Clause License](LICENSE).
