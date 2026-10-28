# Redfish compatibility testing

The compatibility baseline is DMTF Redfish Publication **2026.2**, pinned to
commit `4f81814e399213c9055863ddaff42791c6b3706a`. This is a schema and fixture
baseline, not the SDK package version and not the Redfish protocol version
reported by a BMC.

## Offline SDK checks

The repository contains a small, reviewable selection of official DSP2046
examples under `tests/fixtures/dmtf/2026.2`. The manifest records the upstream
path, model mapping, and SHA-256 digest for every fixture. Normal CI only reads
these committed files and never requires network access, BMC credentials, or a
developer's private `testdata` directory.

Run the deterministic checks with:

```bash
python tools/dmtf_compatibility.py check
pytest
```

The compatibility tests cover standard and legacy aliases, suspended tasks,
referenced registry files, multipart URI spelling, optional links, unknown
future properties, and older single-object task messages. Existing focused
tests continue to cover request encoding and retry behavior.

The historical `tests/test_models_mock.py` suite depends on a complete private
drill capture and is disabled by default, even if a partial `testdata` directory
exists. To run it deliberately, use:

```bash
REDFISH_RUN_LEGACY_TESTDATA=1 \
REDFISH_TESTDATA_DIR=/path/to/complete/testdata \
pytest tests/test_models_mock.py
```

## Reviewing a DMTF baseline update

Refresh operations are intentionally explicit and require network access:

```bash
python tools/dmtf_compatibility.py refresh-fixtures
python tools/dmtf_compatibility.py refresh-report
git diff -- tests/fixtures/dmtf compatibility/dmtf-2026.2-coverage.json
```

The coverage report compares top-level properties in selected DMTF schemas
with Pydantic field aliases. `untyped_schema_properties` are review prompts,
not automatic requirements: Redfish properties are frequently optional, and
the SDK must continue accepting older BMC and OEM payloads. Nested definitions
and normative CSDL differences require human review before model changes.

To adopt another publication, update the release and commit constants, update
the manifest checksums, regenerate both artifacts, and review the diff. Do not
generate mandatory SDK fields solely because a new optional schema property
exists.

## Live service validation

These layers answer different questions and their results must be reported
separately:

1. DMTF Redfish Service Validator and Protocol Validator validate an authorized
   BMC service and its payloads against Redfish requirements.
2. The committed mockups validate SDK parsing and client request behavior.
3. `tests/test_real_bmc.py` validates selected SDK flows against real hardware
   only when `REDFISH_RUN_REAL_BMC=1`, `BMC_IP`, `BMC_USER`, and `BMC_PASSWORD`
   are supplied in an authorized environment.

Run the live layer explicitly with:

```bash
REDFISH_RUN_REAL_BMC=1 pytest tests/test_real_bmc.py -v
```

Do not commit validator captures, credentials, private endpoints, device
identifiers, or hardware results. A live-validation report should identify the
validator and version, DMTF publication, tested service firmware, test scope,
and separate service findings from SDK findings.
