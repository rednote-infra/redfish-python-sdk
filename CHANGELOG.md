# Changelog

All notable changes to redfish-python-sdk will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-11-15

### Added
- Offline-aware asynchronous operation monitoring with task recovery policies and task-monitor support.
- Typed resource aliases and alias-based resource addressing.
- Referenced message-registry resolution and `VendorCode` modeling.
- Current inventory, authentication, and NTP schema fields while retaining compatibility with older payloads.
- UpdateService capability discovery and software-image lifecycle APIs.
- Capability-driven PolicyService discovery and policy lifecycle APIs.
- Standard ComputerSystem graphical-console actions and typed request and response models.
- Standard VirtualMedia insert and eject actions, including `HTTPHeaders` support.
- Modern power-subsystem, power-supply metrics, and sensor discovery APIs.
- Standard Port and PortMetrics discovery with capability-checked transceiver reset support.
- Optional CXL and UALink topology discovery.
- Optional liquid-cooling equipment and fluid-reading discovery.

### Changed
- Collection traversal follows pagination links and reports partial retrieval failures.
- Resource discovery follows service-advertised collection and member links instead of assuming URI layouts.

### Fixed
- Standard multipart firmware updates encode `UpdateParameters` as a JSON part.

## [1.3.0] - 2026-10-12

### Added
- Typed TelemetryService APIs for metric definitions, report definitions, reports, triggers, and metric report logs.
- Optional CompositionService, ResourceBlock, and ResourceZone discovery APIs.
- Typed Manager SerialInterface discovery and configuration with allowable-value validation and ETag handling.
- AMI signing-key and firmware-image uploads, HTTP/multipart push uploads, and BMC firmware update actions with task references.
- Manager reset, single LogService lookup, and log-clearing operations.
- Optional SecureBoot, NetworkInterface/NetworkPort, MemoryDomain, MemoryChunks, and MemoryMetrics APIs.
- Typed action descriptors, ActionInfo metadata, and reset request models with OEM compatibility.
- Standard ManagerNetworkProtocol NTP, SNMP, RFB, and HTTPS certificate collection support.
- MessageId-first EventService test events and MessageSeverity support.
- Enginetech diagnostic log collection and firmware update strategies.

### Changed
- Cached manager cleanup discovers optional service managers automatically.
- PCIe DeviceBDF is explicitly identified as an xFusion OEM extension.

### Fixed
- Nested Memory, BIOS, NetworkProtocol, and VirtualMedia access follows advertised resource links.
- Default Manager and Chassis discovery preserves identifier compatibility and falls back to advertised collection members.
- UpdateService accepts the standard MultipartHttpPushUri property and the legacy spelling.

## [1.2.3] - 2026-09-10

### Added
- PyPI downloads badge in the English README.
- Multi-vendor out-of-band diagnostic log collection and download APIs.
- Brief module descriptions for event models and manager code.

### Changed
- README installation examples now reference `1.2.3`.
- Fan speed ratio and disk temperature documentation was expanded.

## [1.1.0] - 2026-08-04

### Added
- 10 OEM service models: `NtpService`, `SyslogService`, `SnmpService`, `LldpService`, `VncService`, `SecurityService`, `HttpsCert`, `FirewallRules`, `VirtualMedia`, `DnsService`
- 12 new `Client` methods for OEM service access: `get_ntp_service()`, `get_syslog_service()`, `get_snmp_service()`, `get_lldp_service()`, `get_vnc_service()`, `get_security_service()`, `get_https_cert()`, `get_firewall_rules()`, `get_virtual_media_list()`, `get_dns_service()`, `get_sol_source_control_info()`, `get_smtp_service()`
- 11 OEM link fields on `Bmc` model for automatic service URI discovery
- Generic `_get_oem_service()` helper in `ManagersService` to reduce boilerplate for OEM service access
