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
# Online fixtures
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
# Offline fixtures (dynamic parametrization)
# ---------------------------------------------------------------------------


def pytest_generate_tests(metafunc):
    """
    Generate one test set for each JSON data directory.

    When a test declares the ``json_loader`` fixture, scan the directory
    selected by REDFISH_JSON_DIR and create a RedfishJsonLoader for every
    child directory that contains JSON files.
    """
    if "json_loader" not in metafunc.fixturenames:
        return

    json_dir = os.environ.get("REDFISH_JSON_DIR")
    if not json_dir:
        # Provide a placeholder when the environment variable is absent. The
        # test checks for a None loader and skips itself.
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
    """Skip automatically when no JSON data directory is configured."""
    if "json_loader" in request.fixturenames:
        loader = request.getfixturevalue("json_loader")
        if loader is None:
            pytest.skip("REDFISH_JSON_DIR is not set; skipping offline tests")
