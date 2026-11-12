# redfish-python-sdk

> 一个轻量级 Python SDK，用于通过 [DMTF Redfish](https://www.dmtf.org/standards/redfish) 协议管理服务器 BMC（Baseboard Management Controller，基板管理控制器），覆盖系统信息、硬件巡检、电源控制、启动项管理、事件订阅等场景。

[![PyPI version](https://img.shields.io/pypi/v/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![License](https://img.shields.io/pypi/l/redfish-python-sdk)](https://github.com/rednote-infra/redfish-python-sdk/blob/main/LICENSE)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/redfish-python-sdk?period=total&units=INTERNATIONAL_SYSTEM&left_color=GRAY&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/redfish-python-sdk)

[English](README.md) | [中文](README_zh.md)

## 特性

- **硬件信息查询** — 查询 CPU、内存、硬盘、GPU、网卡、PCIe、电源和散热资源
- **电源与启动管理** — 开关机、重启，以及 PXE、磁盘和 BIOS 设置界面的启动覆盖配置
- **多厂商支持** — 支持标准 Redfish 资源和针对性的 OEM 适配，具体能力取决于 BMC 固件
- **Pydantic v2 模型** — 类型化资源查询接口提供数据校验和 IDE 自动补全
- **上下文管理器** — 使用 `with` 自动清理客户端资源
- **最小依赖** — 运行时直接依赖 `requests` 和 `pydantic`

## 安装

要求 Python 3.9 或更高版本；CI 覆盖 Python 3.9–3.13。本文档介绍当前 `main` 分支，已发布的软件包可能有所不同；如需当前源码的行为，请从 GitHub 安装。

```bash
# Install from PyPI
pip install redfish-python-sdk

# Or install the current main branch from GitHub
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@main
```

如需固定发布版本，PyPI 使用 `redfish-python-sdk==VERSION`，Git 安装则将 URL 中的 `@main` 替换为 `@TAG`。

## 快速开始

运行以下只读示例前，请在环境中设置 `BMC_IP`、`BMC_USER` 和 `BMC_PASSWORD`，不要将凭证写入源代码。

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

示例开启 TLS 证书校验。对于使用私有或自签名 CA 的 BMC，可传入 `ca_bundle="/path/to/bmc-ca.pem"`。在可信测试环境中，显式设置 `verify_ssl=False` 可关闭证书校验。

如果 BMC 暴露多个系统或机箱，请向对应的查询方法传入 `system_id` 或 `chassis_id`。

## 贡献

欢迎贡献！请随时提交 Pull Request。

## 许可证

本项目基于 [BSD 3-Clause 许可证](LICENSE) 开源。
