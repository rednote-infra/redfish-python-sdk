"""
pytest fixtures for Redfish SDK integration tests.

Provides:
- bmc_client: session-scoped RedfishClient for online (Real BMC) tests
- json_loader: parametrized RedfishJsonLoader for offline JSON tests
"""

from __future__ import annotations

import os

import pytest

from redfish_sdk import RedfishClient

try:
    from tests.helpers.json_loader import RedfishJsonLoader, discover_json_dirs
except ImportError:
    from helpers.json_loader import RedfishJsonLoader, discover_json_dirs


# ---------------------------------------------------------------------------
# 在线模式 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def bmc_client():
    """
    Session-scoped RedfishClient for real-BMC integration tests.

    Required environment variables:
      BMC_IP        - target BMC IP or hostname
      BMC_USER      - BMC login username
      BMC_PASSWORD  - BMC login password

    If any variable is missing, the test is skipped (fail-safe: never
    fall back to default credentials that could hit a production BMC).
    """
    ip = os.environ.get("BMC_IP")
    user = os.environ.get("BMC_USER")
    pwd = os.environ.get("BMC_PASSWORD")
    if not all([ip, user, pwd]):
        pytest.skip(
            "BMC_IP / BMC_USER / BMC_PASSWORD not set; skipping real-BMC tests"
        )
    client = RedfishClient(host=ip, username=user, password=pwd)
    yield client
    client.close()


# ---------------------------------------------------------------------------
# 离线模式 fixtures（动态参数化）
# ---------------------------------------------------------------------------


def pytest_generate_tests(metafunc):
    """
    动态参数化: 为每个 JSON 数据目录生成一组测试。

    当测试函数声明了 ``json_loader`` fixture 时，
    自动扫描 REDFISH_JSON_DIR 环境变量指定的目录，
    为每个包含 JSON 文件的子目录创建一个 RedfishJsonLoader 实例。
    """
    if "json_loader" not in metafunc.fixturenames:
        return

    json_dir = os.environ.get("REDFISH_JSON_DIR")
    if not json_dir:
        # 未设置环境变量时，提供一个占位参数
        # 测试函数内部会检查 loader 为 None 并 skip
        metafunc.parametrize(
            "json_loader",
            [None],
            ids=["no-REDFISH_JSON_DIR"],
        )
        return

    dirs = discover_json_dirs(json_dir)
    if not dirs:
        metafunc.parametrize(
            "json_loader",
            [None],
            ids=["empty-json-dir"],
        )
        return

    loaders = [RedfishJsonLoader(d) for d in dirs]
    ids = [loader.server_label for loader in loaders]
    metafunc.parametrize("json_loader", loaders, ids=ids)


@pytest.fixture(autouse=True)
def _skip_if_no_json_loader(request):
    """如果 json_loader 为 None（未配置数据目录），自动跳过测试。"""
    if "json_loader" in request.fixturenames:
        loader = request.getfixturevalue("json_loader")
        if loader is None:
            pytest.skip("REDFISH_JSON_DIR 环境变量未设置，跳过离线测试")
