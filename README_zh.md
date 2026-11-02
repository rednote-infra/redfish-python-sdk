# redfish-python-sdk
**redfish-python-sdk** is a type-safe, high-level Python SDK for managing
multi-vendor BMCs and bare-metal servers through the DMTF Redfish API.

[![PyPI version](https://img.shields.io/pypi/v/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![License](https://img.shields.io/pypi/l/redfish-python-sdk)](https://github.com/rednote-infra/redfish-python-sdk/blob/main/LICENSE)

[English](README.md) | [Alternate README](README_zh.md)

> A lightweight Python SDK for managing server BMCs through the
> [DMTF Redfish](https://www.dmtf.org/standards/redfish) protocol, including
> system inventory, hardware inspection, power control, boot configuration,
> and event subscriptions.

## Features

- **Comprehensive hardware queries** — retrieve CPU, memory, drive, GPU,
  network, PCIe, power, and thermal data with concise calls.
- **Power and boot management** — power on, power off, restart, and switch
  PXE, HDD, or BIOS boot targets.
- **Multi-vendor compatibility** — supports OEM extensions from Huawei,
  xFusion, Lenovo, HPE, Dell, and other vendors.
- **Pydantic v2 models** — strongly typed return values with IDE completion.
- **Context manager support** — automatically release connections with `with`.
- **Minimal dependencies** — only `requests`, `pydantic`, and `urllib3`.

## Requirements

- Python >= 3.9
- A reachable Redfish-compliant BMC endpoint

## Installation

```bash
# Install from PyPI
pip install redfish-python-sdk

# Or install from GitHub
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git

# Install a specific version
pip install redfish-python-sdk==1.2.3
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@v1.2.3

# Reference from requirements.txt
# redfish-python-sdk>=1.2.3
```

## Quick start

> **Credential management:** inject all BMC credentials through environment
> variables. Never hard-code them. Before running examples or tests, export
> `BMC_IP`, `BMC_USER`, and `BMC_PASSWORD`.

```python
import os
from redfish_sdk import RedfishClient

# Connect to the BMC using environment variables
client = RedfishClient(
    host=os.environ["BMC_IP"],
    username=os.environ["BMC_USER"],
    password=os.environ["BMC_PASSWORD"],
)

# Get system information
system = client.systems.get()
print(f"Server: {system.manufacturer} {system.model}")
print(f"SN:     {system.serial_number}")
print(f"Power:  {system.power_state}")

# Get CPU information
for cpu in client.get_processors():
    print(f"CPU: {cpu.model}, {cpu.total_cores} cores / {cpu.total_threads} threads")

# Get memory information
for mem in client.get_memory():
    print(f"DIMM: {mem.manufacturer} {(mem.capacity_mib or 0) // 1024} GB")

# Get drive information
for drive in client.get_drives():
    print(f"Drive: {drive.model} {(drive.capacity_bytes or 0) / 1e12:.1f} TB")

# Close the connection
client.close()
```

## Testing

```bash
# Run unit tests without a BMC or environment variables
pytest tests/test_models_mock.py tests/test_client_mock.py -v

# Run offline tests with previously collected JSON data
export REDFISH_JSON_DIR="./testdata"
pytest tests/test_offline_json.py -v

# Run integration tests against an authorized BMC
export BMC_IP="<your-bmc-ip>"
export BMC_USER="<your-bmc-user>"
export BMC_PASSWORD="<your-bmc-password>"
pytest tests/test_real_bmc.py -v
```

## Contributing

Contributions are welcome. Please submit a pull request.

## License

This project is licensed under the [BSD 3-Clause License](LICENSE).
