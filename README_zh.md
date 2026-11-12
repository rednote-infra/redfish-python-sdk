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
- **固件更新** — 通过 Redfish 更新流程升级设备固件
- **快速查找资源** — 按类型和属性发现标准及 OEM 资源，无须硬编码集合路径
- **一键带外日志下载** — 一次调用完成诊断日志采集、等待采集完成和日志包下载
- **异步运维编排** — 使用 `AsyncRedfishClient` 协调多台 BMC 的操作

## 安装

```bash
# Install from PyPI
pip install redfish-python-sdk

# Or install from GitHub
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git

# Install a specific version
pip install redfish-python-sdk==1.4.0
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@v1.4.0
```

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

## 贡献

欢迎贡献！请随时提交 Pull Request。

## 许可证

本项目基于 [BSD 3-Clause 许可证](LICENSE) 开源。
