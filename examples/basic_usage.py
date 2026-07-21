"""
Basic usage examples for the Redfish Python SDK.

This file demonstrates the most common operations:
- System information retrieval
- Hardware inventory (CPU, memory, drives, GPU)
- Power management
- Boot source control
- BMC management
"""

import logging
import os

from redfish_sdk import RedfishClient, RedfishException

# Enable debug logging to see HTTP requests
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


def main():
    # Initialize the client
    # Credentials are read from environment variables:
    #   BMC_IP, BMC_USER, BMC_PASSWORD
    # - verify_ssl=False: Required for self-signed certs (all BMCs)
    # - proxy: Optional HTTP proxy (matches Java's ProxySelector config)
    client = RedfishClient(
        host=os.environ["BMC_IP"],
        username=os.environ["BMC_USER"],
        password=os.environ["BMC_PASSWORD"],
        verify_ssl=False,
        # proxy="http://127.0.0.1:8080",  # Uncomment if proxy is needed
    )

    try:
        # ----------------------------------------------------------------
        # Root service info
        # ----------------------------------------------------------------
        root = client.root()
        print("\n=== Redfish Root Service ===")
        print(f"  Version: {root.redfish_version}")
        print(f"  Vendor:  {root.vendor}")

        # ----------------------------------------------------------------
        # System information
        # ----------------------------------------------------------------
        print("\n=== System Information ===")
        system = client.get_system()
        print(f"  Manufacturer: {system.manufacturer}")
        print(f"  Model:        {system.model}")
        print(f"  Serial:       {system.serial_number}")
        print(f"  BIOS:         {system.bios_version}")
        print(f"  Power State:  {system.power_state}")
        print(f"  UUID:         {system.uuid}")

        # ----------------------------------------------------------------
        # CPU information
        # ----------------------------------------------------------------
        print("\n=== Processors ===")
        processors = client.get_processors()
        for cpu in processors.members or []:
            print(f"  [{cpu.id}] {cpu.model}")
            print(
                f"       Socket: {cpu.socket}, Cores: {cpu.total_cores}, Threads: {cpu.total_threads}"
            )
            print(f"       Speed: {cpu.max_speed_mhz} MHz")
            if cpu.status:
                print(f"       Status: {cpu.status.health}")

        # ----------------------------------------------------------------
        # Memory information
        # ----------------------------------------------------------------
        print("\n=== Memory ===")
        memories = client.get_memory()
        total_gib = 0
        for mem in memories.members or []:
            capacity_gib = (mem.capacity_mib or 0) / 1024
            total_gib += capacity_gib
            print(
                f"  [{mem.device_locator or mem.id}] {mem.manufacturer} {capacity_gib:.0f} GiB "
                f"@ {mem.operating_speed_mhz} MHz ({mem.memory_device_type})"
            )
        print(f"  Total: {total_gib:.0f} GiB")

        # ----------------------------------------------------------------
        # Storage information
        # ----------------------------------------------------------------
        print("\n=== Storage Controllers ===")
        storages = client.get_storages()
        for storage in storages.members or []:
            print(f"  [{storage.id}] {storage.name}")
            if storage.storage_controllers:
                for ctrl in storage.storage_controllers:
                    print(
                        f"    Controller: {ctrl.manufacturer} {ctrl.model} "
                        f"FW: {ctrl.firmware_version}"
                    )

        # ----------------------------------------------------------------
        # Drives (from Chassis)
        # ----------------------------------------------------------------
        print("\n=== Physical Drives ===")
        drives = client.get_drives("1")
        for drive in drives.members or []:
            capacity_gb = (drive.capacity_bytes or 0) / 1e9
            print(
                f"  [{drive.id}] {drive.manufacturer} {drive.model} "
                f"{capacity_gb:.0f} GB {drive.protocol} ({drive.media_type})"
            )
            print(
                f"       SN: {drive.serial_number}, Status: {drive.status.health if drive.status else 'N/A'}"
            )

        # ----------------------------------------------------------------
        # GPU information
        # ----------------------------------------------------------------
        print("\n=== GPUs ===")
        gpus = client.get_gpus()
        if not gpus.members:
            print("  No GPUs found")
        for gpu in gpus.members or []:
            print(f"  [{gpu.id or gpu.name}] {gpu.manufacturer} {gpu.model}")
            print(f"       Version: {gpu.version}, Power: {gpu.power_watts} W")
            if gpu.oem:
                print(f"       SN: {gpu.oem.serial_number}")

        # ----------------------------------------------------------------
        # Network adapters
        # ----------------------------------------------------------------
        print("\n=== Network Adapters ===")
        nics = client.get_network_adapters("1")
        for nic in nics.members or []:
            print(
                f"  [{nic.id}] {nic.manufacturer} {nic.model} SN: {nic.serial_number}"
            )

        # ----------------------------------------------------------------
        # Power supply units
        # ----------------------------------------------------------------
        print("\n=== Power Supplies ===")
        power = client.get_power("1")
        for psu in power.power_supplies or []:
            print(f"  [{psu.member_id or psu.id}] {psu.manufacturer} {psu.model}")
            print(
                f"       Capacity: {psu.power_capacity_watts} W, "
                f"Input: {psu.power_input_watts} W, Output: {psu.power_output_watts} W"
            )
            print(f"       FW: {psu.firmware_version}, SN: {psu.serial_number}")
            if psu.status:
                print(f"       Status: {psu.status.health}")

        # ----------------------------------------------------------------
        # Thermal (temperatures and fans)
        # ----------------------------------------------------------------
        print("\n=== Thermal ===")
        thermal = client.get_thermal("1")
        print("  Temperatures:")
        for temp in (thermal.temperatures or [])[:5]:  # Show first 5
            print(
                f"    {temp.name or temp.member_id}: {temp.reading_celsius}°C "
                f"(Critical: {temp.upper_threshold_critical}°C)"
            )
        print("  Fans:")
        for fan in (thermal.fans or [])[:5]:  # Show first 5
            print(
                f"    {fan.name or fan.member_id}: {fan.reading} {fan.reading_units or 'RPM'}"
            )

        # ----------------------------------------------------------------
        # BMC Manager
        # ----------------------------------------------------------------
        print("\n=== BMC Manager ===")
        manager = client.get_manager("1")
        print(f"  Model:    {manager.model}")
        print(f"  FW:       {manager.firmware_version}")
        print(f"  UUID:     {manager.uuid}")

        # ----------------------------------------------------------------
        # BIOS info
        # ----------------------------------------------------------------
        print("\n=== BIOS ===")
        bios = client.get_bios()
        print(f"  Version: {bios.bios_version}")

    except RedfishException as exc:
        print(f"\nRedfish error: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
