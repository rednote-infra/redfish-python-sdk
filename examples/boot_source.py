"""
Boot source control examples — demonstrates changing server boot source via Redfish.

Common boot targets:
- Pxe:       Boot from PXE network
- Hdd:       Boot from HDD
- Cd:        Boot from CD/DVD/USB
- BiosSetup: Boot into BIOS setup menu
- None:      Use default boot order (clear override)
"""
import os

from redfish_sdk import RedfishClient, RedfishException, RedfishValidationError


def main():
    # Credentials are read from environment variables:
    #   BMC_IP, BMC_USER, BMC_PASSWORD
    client = RedfishClient(
        host=os.environ["BMC_IP"],
        username=os.environ["BMC_USER"],
        password=os.environ["BMC_PASSWORD"],
        verify_ssl=False,
    )

    try:
        # Get current boot settings
        system = client.get_system()
        boot = system.boot
        if boot:
            print(f"Current boot target:  {boot.boot_source_override_target}")
            print(f"Override enabled:     {boot.boot_source_override_enabled}")
            print(f"Override mode:        {boot.boot_source_override_mode}")
            print(f"Allowable values:     {boot.allowable_values}")

        # Change boot source to PXE for next boot only
        print("\nChanging boot source to Pxe (Once)...")
        result = client.change_boot_source(
            target="Pxe",
            enabled="Once",   # "Once" means only next boot, then reverts to default
            mode="UEFI",      # "UEFI" or "Legacy"
        )
        print(f"Boot source changed: {result}")

    except RedfishValidationError as exc:
        print(f"Validation error: {exc}")
    except RedfishException as exc:
        print(f"Redfish error: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
