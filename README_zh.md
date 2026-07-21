# Redfish Python SDK

[English](README.md) | [中文](README_zh.md)

> 一个轻量级 Python SDK，用于通过 [DMTF Redfish](https://www.dmtf.org/standards/redfish) 协议管理服务器 BMC（Baseboard Management Controller），覆盖系统信息、硬件巡检、电源控制、启动项管理、事件订阅等场景。

## 特性

- **全面的硬件查询** — CPU、内存、硬盘、GPU、网卡、PCIe、电源、散热，一行代码获取
- **电源与启动管理** — 开关机、重启、PXE/HDD/BIOS 启动项切换
- **多厂商兼容** — 自动适配华为/超聚变/联想/HPE/Dell 等厂商的 OEM 扩展字段
- **Pydantic v2 模型** — 所有返回值均为强类型对象，IDE 自动补全友好
- **上下文管理器** — 支持 `with` 语句自动释放连接
- **最小依赖** — 仅依赖 `requests`、`pydantic`、`urllib3`

## 环境要求

- Python >= 3.9
- 网络可达的 Redfish-compliant BMC 端点

## 安装

```bash
# 从 PyPI 安装
pip install redfish-python-sdk

# 或从 GitHub 安装
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git

# 安装指定版本
pip install redfish-python-sdk==1.0.0
pip install git+https://github.com/rednote-infra/redfish-python-sdk.git@v1.0.0

# 在 requirements.txt 中引用
# redfish-python-sdk>=1.0.0
```

## 快速开始

> **凭证管理**：所有 BMC 凭证都通过环境变量注入，**不要**在代码里硬编码。
> 在运行示例 / 测试前先 `export BMC_IP=...`、`export BMC_USER=...`、`export BMC_PASSWORD=...`，详见下文[环境变量](#环境变量)一节。

```python
import os
from redfish_sdk import RedfishClient

# 通过环境变量连接 BMC
client = RedfishClient(
    host=os.environ["BMC_IP"],
    username=os.environ["BMC_USER"],
    password=os.environ["BMC_PASSWORD"],
)

# 获取系统信息
system = client.systems.get()
print(f"Server: {system.manufacturer} {system.model}")
print(f"SN:     {system.serial_number}")
print(f"Power:  {system.power_state}")

# 获取 CPU 信息
for cpu in client.get_processors():
    print(f"CPU: {cpu.model}, {cpu.total_cores} cores / {cpu.total_threads} threads")

# 获取内存信息
for mem in client.get_memory():
    print(f"DIMM: {mem.manufacturer} {(mem.capacity_mib or 0) // 1024} GB")

# 获取硬盘信息
for drive in client.get_drives():
    print(f"Drive: {drive.model} {(drive.capacity_bytes or 0) / 1e12:.1f} TB")

# 记得关闭连接
client.close()
```

## 进阶用法

### 上下文管理器

```python
import os
from redfish_sdk import RedfishClient

with RedfishClient(
    host=os.environ["BMC_IP"],
    username=os.environ["BMC_USER"],
    password=os.environ["BMC_PASSWORD"],
) as client:
    system = client.systems.get()
    print(system.serial_number)
# 自动关闭连接
```

### 电源控制

```python
# 电源操作
client.power_on()
client.power_off()        # 优雅关机
client.force_power_off()  # 强制断电
client.power_restart()    # 优雅重启

# 设置下次启动项
client.set_boot_source("Pxe")        # PXE 网络启动
client.set_boot_source("Hdd")        # 硬盘启动
client.set_boot_source("BiosSetup")  # 进入 BIOS 设置
```

### 硬件巡检

```python
# GPU 信息
for gpu in client.get_gpus():
    print(f"GPU: {gpu.manufacturer} {gpu.model}")

# 网卡信息
for nic in client.get_network_adapters():
    print(f"NIC: {nic.manufacturer} {nic.model}")

# PCIe 设备
for dev in client.get_pcie_devices():
    print(f"PCIe: {dev.manufacturer} {dev.model}")

# 电源信息
for psu in client.get_power_supplies():
    print(f"PSU: {psu.model}, {psu.power_capacity_watts}W")

# 散热传感器
for fan in client.get_fans():
    print(f"Fan: {fan.name}, {fan.reading} RPM")
for temp in client.get_temperatures():
    print(f"Temp: {temp.name}, {temp.reading_celsius}°C")
```

### 事件订阅

```python
# 订阅 Redfish 事件
subscription = client.subscribe(
    destination="https://my-listener:8080/events",
    event_types=["Alert"],
    context="my-monitor",
)

# 列出已有订阅
for sub in client.get_subscriptions():
    print(f"Subscription: {sub.id} -> {sub.destination}")

# 删除订阅
client.delete_subscription(subscription.id)
```

### 异常处理

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
    print("认证失败")
except RedfishException as e:
    print(f"Redfish 错误: {e}")
```

异常类层级：

```
RedfishException           # 基础异常
├── RedfishNotFoundError   # 404 — 资源不存在
├── RedfishAuthError       # 401/403 — 认证失败
├── RedfishConnectionError # 网络连接失败
├── RedfishTimeoutError    # 请求超时
└── RedfishValidationError # 参数校验失败（如不支持的 reset type）
```

## 环境变量

SDK 本身不读环境变量；下列变量由示例代码、工具脚本与集成测试使用：

| 变量 | 用途 | 示例 |
|---|---|---|
| `BMC_IP` | 目标 BMC 的 IP 或主机名 | `192.168.1.100` |
| `BMC_USER` | BMC 登录用户名 | `admin` |
| `BMC_PASSWORD` | BMC 登录密码 | `password` |
| `REDFISH_JSON_DIR` | 离线 JSON 测试数据目录 | `./testdata` |

**约定**：集成测试 / 工具脚本若未设置必需变量，会显式跳过或 `SystemExit`，避免使用默认凭证误连生产 BMC。建议结合 `direnv` 或本机 shell rc 文件管理。

## 测试

```bash
# 运行单元测试（无需 BMC / env）
pytest tests/test_models_mock.py tests/test_client_mock.py -v

# 运行离线测试（使用预采集的 JSON 数据）
export REDFISH_JSON_DIR="./testdata"
pytest tests/test_offline_json.py -v

# 运行集成测试（需要连接真实 BMC，凭证从环境变量读取）
export BMC_IP="<your-bmc-ip>"
export BMC_USER="<your-bmc-user>"
export BMC_PASSWORD="<your-bmc-password>"
pytest tests/test_real_bmc.py -v
```

## 贡献

欢迎贡献！请随时提交 Pull Request。

## 许可证

本项目基于 [BSD 3-Clause 许可证](LICENSE) 开源。
