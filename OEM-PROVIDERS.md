# Installable OEM providers (interface v1)

Downstream packages can extend firmware updates, diagnostic-log collection, or
OEM field extraction without editing SDK code or its global built-in registries.

## Provider contract

Implement the relevant public base class from `redfish_sdk.oem`:

| Entry-point group | Base interface | Main hooks |
| --- | --- | --- |
| `redfish_sdk.oem.v1.update` | `BaseUpdateStrategy` | `execute(client, image_uri, transfer_protocol="HTTP", targets=None, **kwargs)` |
| `redfish_sdk.oem.v1.log_collect` | `BaseLogCollectStrategy` | `resolve_log_services_odata_id`, `discover_collect_target`, `build_collect_body`, `download_artifact` and inherited hooks |
| `redfish_sdk.oem.v1.extractor` | `BaseOemExtractor` | `get_fan_speed_ratio(fan)`, `get_drive_temperature_celsius(drive)` |

Return the same types as the corresponding base methods. Inherit default hooks
instead of copying them. Entry-point targets may be a base-interface instance
or a zero-argument class/factory that returns one. Factory/import failures are
cached and reported as `OemProviderLoadError`, with the original exception as
its cause on initial failure. Runtime operation failures propagate normally;
the SDK does not retry an OEM write on another provider.

Example downstream `pyproject.toml`:

```toml
[project.entry-points."redfish_sdk.oem.v1.extractor"]
example = "example_oem:ExampleExtractor"
```

```python
from redfish_sdk.oem import BaseOemExtractor

class ExampleExtractor(BaseOemExtractor):
    def get_fan_speed_ratio(self, fan):
        # Implement your vendor's contract; None means no known reading.
        return super().get_fan_speed_ratio(fan)
```

Entry-point names are vendor keys, normalized to lowercase. Existing vendor
detector keys and built-in strategies are unchanged. For a new vendor not
recognized by the built-in detector, pass `oem_vendor="example"` to
`RedfishClient`. A per-call `simple_update(vendor=...)` still takes precedence.

## Precedence and isolation

Each client gets its own `OemProviderRegistry` unless one is injected:

1. Explicit registrations on that registry.
2. Existing built-in provider for that vendor/category.
3. Installed entry-point provider.
4. Existing generic fallback if nothing matches.

`allow_builtin_overrides=True` moves discovered providers ahead of built-ins;
this must be an intentional choice by the application. Duplicate installed
entries for a selected vendor/category raise `OemProviderConflictError` without
loading either. Duplicate explicit registrations also raise that error.
Conflicts do not depend on package enumeration order. A broken optional plugin
is loaded only when selected and cannot disable another vendor. Do not silently
fall back after a selected plugin fails: this could run an incorrect OEM write.

Discovery is lazy and snapshotted once per registry. Providers are initialized
once per selected key; lookups and initialization are serialized. Create a new
registry to rediscover newly installed packages. Explicit registration can
replace a previously discovered provider without changing another client's
registry. Share a registry between clients only when shared provider instances
are appropriate; providers are responsible for their own operation-time state
and thread safety. Legacy global `*Registry.register/get` APIs still work.

## Deterministic embedding

```python
from redfish_sdk import OemCategory, OemProviderRegistry, RedfishClient

providers = OemProviderRegistry(discover=False)
providers.register(OemCategory.EXTRACTOR, "example", ExampleExtractor())
client = RedfishClient(
    host="bmc.example", username="operator", password="<from-secret-store>",
    verify_ssl=True, oem_vendor="example", oem_providers=providers,
)
```

`discover=False` prevents all metadata enumeration and optional entry-point
imports. Alternatively, inject `entry_points=lambda: chosen_entry_points` to
replace installed-package enumeration with an allowlist of EntryPoint-compatible
objects (`name`, `group`, `value`, `load()`). Disable discovery or provide an empty
allowlist to retain explicit/built-in providers only. The same parameters work
for tests. Built-ins continue to work if package enumeration itself fails;
unknown vendors then receive a clear discovery error.

## Security and compatibility

Providers are trusted executable Python code, not a sandbox. Imports, factories,
and operations run with application privileges; update/log strategies receive
the authenticated client and can issue BMC writes or access credentials. Install
only reviewed distributions, pin dependencies, and use an allowlist or disable
discovery in controlled environments. Factories should not perform BMC/network
operations. Avoid logging credentials, tokens, console URLs, or private device
data. Do not register global providers as an import side effect.

The `.v1` group names and public base method contracts define interface version
1. A future incompatible contract will use a new group version. Declare and test
compatible SDK dependency bounds in the downstream package; inherited additive
hooks may gain implementations. Private SDK helpers and internal registry
dictionaries are not part of the provider compatibility guarantee. Test on the
SDK's supported Python versions and on the relevant vendor firmware.
