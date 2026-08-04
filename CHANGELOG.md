# Changelog

All notable changes to redfish-python-sdk will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-08-04

### Added
- 10 OEM service models: `NtpService`, `SyslogService`, `SnmpService`, `LldpService`, `VncService`, `SecurityService`, `HttpsCert`, `FirewallRules`, `VirtualMedia`, `DnsService`
- 12 new `Client` methods for OEM service access: `get_ntp_service()`, `get_syslog_service()`, `get_snmp_service()`, `get_lldp_service()`, `get_vnc_service()`, `get_security_service()`, `get_https_cert()`, `get_firewall_rules()`, `get_virtual_media_list()`, `get_dns_service()`, `get_sol_source_control_info()`, `get_smtp_service()`
- 11 OEM link fields on `Bmc` model for automatic service URI discovery
- Generic `_get_oem_service()` helper in `ManagersService` to reduce boilerplate for OEM service access
