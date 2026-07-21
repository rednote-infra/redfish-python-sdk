# Redfish Python SDK

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
pip install redfish-python-sdk==1.0.0
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@v1.0.0

# In requirements.txt
# redfish-python-sdk>=1.0.0
```

## Quick Start

> **Credential management**: All BMC credentials should be injected via environment variables. **Never** hardcode them in your source code.
> Before running examples or tests, set `export BMC_IP=...`, `export BMC_USER=...`, `export BMC_PASSWORD=...`. See the [Environment Variables](#environment-variables) section below.

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

## Error Handling

```python
import os
from redfish_sdk import RedfishClient, RedfishException, RedfishAuthError

try:
    client = RedfishClient(
        host=os.environ["BMC_IP"],
        username=os.environ["BMC_USER"],
        password=os.environ["BMC_PASSWORD"],
    )
    system = client.systems.get()
except RedfishAuthError:
    print("Authentication failed")
except RedfishException as e:
    print(f"Redfish error: {e}")
```

Exception hierarchy:

```
RedfishException           # Base exception
├── RedfishNotFoundError   # 404 — resource not found
├── RedfishAuthError       # 401/403 — authentication failure
├── RedfishConnectionError # Network connection failure
├── RedfishTimeoutError    # Request timeout
└── RedfishValidationError # Parameter validation failure (e.g., unsupported reset type)
```

## Environment Variables

The SDK itself does not read environment variables. The following variables are used by example scripts, tools, and integration tests:

| Variable | Purpose | Example |
|---|---|---|
| `BMC_IP` | Target BMC IP or hostname | `192.168.1.100` |
| `BMC_USER` | BMC login username | `admin` |
| `BMC_PASSWORD` | BMC login password | `password` |
| `REDFISH_JSON_DIR` | Offline JSON test data directory | `./testdata` |

**Convention**: Integration tests and tool scripts will explicitly skip or `SystemExit` when required variables are not set, preventing accidental connections to production BMCs with default credentials. Consider using `direnv` or shell profile files to manage these variables.

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
