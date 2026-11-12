"""Optional OEM providers, isolation, precedence, and real wheel installation."""
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from importlib.metadata import EntryPoint
from pathlib import Path
from unittest.mock import Mock

import pytest

from redfish_sdk import RedfishClient
from redfish_sdk.managers.log_collect_strategies import GenericLogCollectStrategy
from redfish_sdk.managers.oem_extractors import GenericOemExtractor, OemExtractorRegistry
from redfish_sdk.managers.update_strategies import GenericUpdateStrategy, UpdateStrategyRegistry
from redfish_sdk.models.common import RedfishResponse
from redfish_sdk.models.task import Task


class Extractor(GenericOemExtractor):
    def get_fan_speed_ratio(self, fan):
        return 87.5


class Update(GenericUpdateStrategy):
    def execute(self, client, image_uri, transfer_protocol="HTTP", targets=None, **kwargs):
        return RedfishResponse.model_validate({"Message": "External update"})


class Logs(GenericLogCollectStrategy):
    def download_artifact(self, client, task, output_path=None):
        return b"external logs"


def entry(category, vendor, value=None):
    from redfish_sdk.oem import OEM_ENTRY_POINT_PREFIX
    point = Mock()
    point.name = vendor
    point.group = f"{OEM_ENTRY_POINT_PREFIX}.{category}"
    point.value = f"example:{vendor}"
    point.load.return_value = value or Extractor
    return point


def test_discovery_is_lazy_and_disabled_discovery_never_runs():
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    load = Mock(return_value=[])
    registry = OemProviderRegistry(discover=False, entry_points=load)
    assert isinstance(registry.get(OemCategory.EXTRACTOR, "example"), GenericOemExtractor)
    load.assert_not_called()
    registry = OemProviderRegistry(entry_points=load)
    load.assert_not_called()
    registry.get(OemCategory.EXTRACTOR, "example")
    load.assert_called_once()


@pytest.mark.parametrize(("category", "implementation"), [("update", Update), ("log_collect", Logs), ("extractor", Extractor)])
def test_entry_point_provider_is_loaded_once(category, implementation):
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    point = entry(category, "EXAMPLE", implementation)
    registry = OemProviderRegistry(entry_points=lambda: [point])
    assert isinstance(registry.get(OemCategory(category), "example"), implementation)
    assert isinstance(registry.get(OemCategory(category), "EXAMPLE"), implementation)
    point.load.assert_called_once()


def test_builtins_are_protected_unless_explicitly_overridden():
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    point = entry("extractor", "zte")
    registry = OemProviderRegistry(entry_points=lambda: [point])
    assert registry.get(OemCategory.EXTRACTOR, "zte") is OemExtractorRegistry.get("zte")
    point.load.assert_not_called()
    registry = OemProviderRegistry(entry_points=lambda: [point], allow_builtin_overrides=True)
    assert isinstance(registry.get(OemCategory.EXTRACTOR, "zte"), Extractor)


def test_explicit_registration_has_highest_priority_and_is_per_registry():
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    instance = Extractor()
    point = entry("extractor", "zte")
    registry = OemProviderRegistry(entry_points=lambda: [point])
    registry.register(OemCategory.EXTRACTOR, "zte", instance)
    assert registry.get(OemCategory.EXTRACTOR, "zte") is instance
    assert not isinstance(OemProviderRegistry(discover=False).get(OemCategory.EXTRACTOR, "zte"), Extractor)
    assert OemExtractorRegistry.get("zte") is not instance
    point.load.assert_not_called()


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_plugins_fail_only_for_the_conflicting_key(reverse):
    from redfish_sdk.oem import OemCategory, OemProviderConflictError, OemProviderRegistry
    points = [entry("extractor", "example"), entry("extractor", "EXAMPLE"), entry("extractor", "other")]
    registry = OemProviderRegistry(entry_points=lambda: list(reversed(points)) if reverse else points)
    with pytest.raises(OemProviderConflictError):
        registry.get(OemCategory.EXTRACTOR, "example")
    assert isinstance(registry.get(OemCategory.EXTRACTOR, "other"), Extractor)
    points[0].load.assert_not_called()
    points[1].load.assert_not_called()


def test_broken_provider_is_reported_without_importing_unrelated_providers(caplog):
    from redfish_sdk.oem import OemCategory, OemProviderLoadError, OemProviderRegistry
    broken, healthy = entry("extractor", "broken"), entry("extractor", "healthy")
    broken.load.side_effect = ImportError("missing dependency")
    registry = OemProviderRegistry(entry_points=lambda: [broken, healthy])
    assert isinstance(registry.get(OemCategory.EXTRACTOR, "healthy"), Extractor)
    broken.load.assert_not_called()
    for _ in range(2):
        with pytest.raises(OemProviderLoadError):
            registry.get(OemCategory.EXTRACTOR, "broken")
    broken.load.assert_called_once()
    assert "broken" in caplog.text and "ImportError" in caplog.text


def test_invalid_provider_is_rejected_and_explicit_conflicts_are_errors():
    from redfish_sdk.oem import OemCategory, OemProviderConflictError, OemProviderLoadError, OemProviderRegistry
    registry = OemProviderRegistry(entry_points=lambda: [entry("extractor", "bad", object)])
    with pytest.raises(OemProviderLoadError):
        registry.get(OemCategory.EXTRACTOR, "bad")
    registry.register(OemCategory.EXTRACTOR, "explicit", Extractor())
    with pytest.raises(OemProviderConflictError):
        registry.register(OemCategory.EXTRACTOR, "explicit", Extractor())


def test_client_dispatches_all_categories_without_vendor_detector_changes():
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    providers = OemProviderRegistry(discover=False)
    providers.register(OemCategory.EXTRACTOR, "example", Extractor())
    providers.register(OemCategory.UPDATE, "example", Update())
    providers.register(OemCategory.LOG_COLLECT, "example", Logs())
    with RedfishClient("example.test", "test", "test", verify_ssl=True,
                       oem_vendor="example", oem_providers=providers) as client:
        assert client._chassis.get_fan_speed_ratio(object()) == 87.5
        assert client.simple_update("https://example.test/image").message == "External update"
        assert client.download_diagnostic_data(Task.model_construct()) == b"external logs"


def test_existing_registry_keys_and_instances_remain_unchanged():
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    providers = OemProviderRegistry(discover=False)
    for vendor in UpdateStrategyRegistry.registered_vendors():
        assert providers.get(OemCategory.UPDATE, vendor) is UpdateStrategyRegistry.get(vendor)


def test_separately_installed_wheel_registers_a_provider(tmp_path, monkeypatch):
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    wheel = tmp_path / "example_oem-1.0-py3-none-any.whl"
    info = "example_oem-1.0.dist-info"
    module = ("from redfish_sdk.oem import BaseOemExtractor\nclass External(BaseOemExtractor):\n"
              "    def get_fan_speed_ratio(self, fan):\n        return 62.5\n")
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("example_oem.py", module)
        archive.writestr(f"{info}/METADATA", "Metadata-Version: 2.1\nName: example-oem\nVersion: 1.0\n")
        archive.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(f"{info}/entry_points.txt", "[redfish_sdk.oem.v1.extractor]\ninstalled-example = example_oem:External\n")
        archive.writestr(f"{info}/RECORD", "")
    target = tmp_path / "installed"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--target", str(target), str(wheel)],
                   check=True, capture_output=True, text=True)
    monkeypatch.syspath_prepend(str(target))
    try:
        registry = OemProviderRegistry()
        implementation = registry.get(OemCategory.EXTRACTOR, "installed-example")
        assert type(implementation).__module__ == "example_oem"
        assert isinstance(implementation, import_module("example_oem").External)
        with RedfishClient("example.test", "test", "test", verify_ssl=True,
                           oem_vendor="installed-example") as client:
            assert client._chassis.get_fan_speed_ratio(object()) == 62.5
    finally:
        sys.modules.pop("example_oem", None)


def test_real_entry_point_objects_can_replace_discovery(monkeypatch):
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    point = EntryPoint(name="example", value="test_oem_providers:Extractor", group="redfish_sdk.oem.v1.extractor")
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    assert isinstance(OemProviderRegistry(entry_points=lambda: [point]).get(OemCategory.EXTRACTOR, "example"),
                      GenericOemExtractor)


def test_concurrent_lookups_initialize_provider_only_once():
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    point = entry("extractor", "example")
    registry = OemProviderRegistry(entry_points=lambda: [point])
    with ThreadPoolExecutor(max_workers=4) as pool:
        providers = list(pool.map(lambda _: registry.get(OemCategory.EXTRACTOR, "example"), range(8)))
    assert all(provider is providers[0] for provider in providers)
    point.load.assert_called_once()


def test_metadata_failure_preserves_builtins_and_is_reported_for_unknown_vendor():
    from redfish_sdk.oem import OemCategory, OemProviderLoadError, OemProviderRegistry
    loader = Mock(side_effect=RuntimeError("bad metadata"))
    registry = OemProviderRegistry(entry_points=loader, allow_builtin_overrides=True)
    assert registry.get(OemCategory.EXTRACTOR, "zte") is OemExtractorRegistry.get("zte")
    with pytest.raises(OemProviderLoadError, match="enumerate"):
        registry.get(OemCategory.EXTRACTOR, "example")
    loader.assert_called_once()


def test_python39_mapping_entry_points_are_supported(monkeypatch):
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    point = entry("extractor", "example")
    monkeypatch.setattr("redfish_sdk.managers.oem_providers.metadata.entry_points", lambda: {point.group: [point]})
    assert isinstance(OemProviderRegistry().get(OemCategory.EXTRACTOR, "example"), Extractor)


def test_unsupported_entry_point_group_is_not_loaded():
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    point = entry("extractor", "example")
    point.group = "redfish_sdk.oem.v999.extractor"
    registry = OemProviderRegistry(entry_points=lambda: [point])
    assert isinstance(registry.get(OemCategory.EXTRACTOR, "example"), GenericOemExtractor)
    point.load.assert_not_called()


def test_invalid_explicit_provider_and_client_options_are_rejected():
    from redfish_sdk import RedfishValidationError
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    with pytest.raises(RedfishValidationError):
        OemProviderRegistry().register(OemCategory.EXTRACTOR, "example", object())
    for options in ({"oem_providers": object()}, {"oem_vendor": ""}):
        with pytest.raises(RedfishValidationError):
            RedfishClient("example.test", "test", "test", verify_ssl=True, **options)


def test_provider_operation_errors_propagate_without_fallback():
    from redfish_sdk.oem import OemCategory, OemProviderRegistry
    implementation = Update()
    failure = RuntimeError("Operation failed")
    implementation.execute = Mock(side_effect=failure)
    registry = OemProviderRegistry(discover=False)
    registry.register(OemCategory.UPDATE, "example", implementation)
    with RedfishClient("example.test", "test", "test", verify_ssl=True,
                       oem_vendor="example", oem_providers=registry) as client:
        with pytest.raises(RuntimeError) as caught:
            client.simple_update("https://example.test/image")
        assert caught.value is failure
        implementation.execute.assert_called_once()


def test_public_facade_reexports_the_shared_manager_implementation():
    from redfish_sdk import oem
    from redfish_sdk.managers import oem_providers
    for name in oem.__all__:
        assert getattr(oem, name) is getattr(oem_providers, name)
    assert oem.OemProviderRegistry.__module__ == "redfish_sdk.managers.oem_providers"


@pytest.mark.parametrize("module", ["redfish_sdk.oem", "redfish_sdk.managers.oem_providers", "redfish_sdk.client"])
def test_provider_import_paths_work_in_fresh_interpreter(module):
    subprocess.run([sys.executable, "-c", f"import {module}"], check=True, capture_output=True, text=True)
