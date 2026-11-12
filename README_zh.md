# redfish-python-sdk

> 一个轻量级 Python SDK，用于通过 [DMTF Redfish](https://www.dmtf.org/standards/redfish) 协议管理服务器 BMC（Baseboard Management Controller，基板管理控制器），覆盖系统信息、硬件巡检、电源控制、启动项管理、事件订阅等场景。

[![PyPI version](https://img.shields.io/pypi/v/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![Python versions](https://img.shields.io/pypi/pyversions/redfish-python-sdk)](https://pypi.org/project/redfish-python-sdk/)
[![License](https://img.shields.io/pypi/l/redfish-python-sdk)](https://github.com/rednote-infra/redfish-python-sdk/blob/main/LICENSE)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/redfish-python-sdk?period=total&units=INTERNATIONAL_SYSTEM&left_color=GRAY&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/redfish-python-sdk)

[English](README.md) | [中文](README_zh.md)

## 特性

- **多厂商硬件巡检** — 通过一个 SDK 查询 CPU、内存、GPU、存储、网络、电源和散热信息
- **远程电源与启动控制** — 开关机、重启，以及选择 PXE、磁盘或 BIOS 设置界面启动
- **BIOS 配置管理** — 更新待生效设置前检查属性值，并安排变更的生效时间
- **固件更新与故障诊断** — 更新固件，采集并下载诊断日志包，辅助故障排查
- **快速查找资源** — 按类型和属性发现标准及 OEM 资源，无须硬编码集合路径
- **变更先看后改** — 查看配置差异、校验并试运行变更，再按顺序提交
- **异步运维编排** — 使用 `AsyncRedfishClient` 协调多台 BMC 的操作

## 安装

```bash
# Install from PyPI
pip install redfish-python-sdk

# Or install the current main branch from GitHub
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@main
```

如需固定发布版本，PyPI 使用 `redfish-python-sdk==VERSION`，Git 安装则将 URL 中的 `@main` 替换为 `@TAG`。

## 快速开始

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
