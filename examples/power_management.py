"""
Power management examples — demonstrates server power control via Redfish.

Supported reset types:
- On: Power on (only when server is off)
- ForceOff: Hard power off (immediate, no OS shutdown)
- GracefulShutdown: Soft power off (requests OS to shut down gracefully)
- GracefulRestart: Soft reboot (requests OS to restart gracefully)
- ForceRestart: Hard reboot (immediate power cycle)
- Nmi: Send NMI (Non-Maskable Interrupt, for debug/crash dump)
- PushPowerButton: Simulate pressing the physical power button
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
        # Check current power state
        system = client.get_system()
        print(f"Current power state: {system.power_state}")

        if system.power_state == "On":
            # Graceful restart (recommended approach)
            print("Sending GracefulRestart...")
            response = client.reset("GracefulRestart")
            print(f"Reset response: {response}")

        elif system.power_state == "Off":
            # Power on
            print("Powering on...")
            response = client.reset("On")
            print(f"Power on response: {response}")

    except RedfishValidationError as exc:
        # Raised when reset type is incompatible with current power state
        print(f"Validation error: {exc}")
    except RedfishException as exc:
        print(f"Redfish error: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
