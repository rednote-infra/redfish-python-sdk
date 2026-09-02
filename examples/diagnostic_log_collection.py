"""
Out-of-band diagnostic log collection examples.

Demonstrates triggering a multi-vendor Redfish
``#LogService.CollectDiagnosticData`` action and downloading the produced
diagnostic bundle. The SDK auto-detects the server vendor (xFusion, Lenovo,
Inspur, Nettrix, ZTE) and falls back to the standard DMTF body for others.

Three usage levels:
- collect_diagnostic_data:              trigger only, returns a Task
- download_diagnostic_data:             download a finished bundle
- collect_and_download_diagnostic_data: one-click end-to-end helper
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
        # --- One-click: trigger, wait, and download in a single call ---
        output_path = os.environ.get("OUTPUT_PATH", "./diagnostic_bundle.tar.gz")
        print("Collecting diagnostic data (this can take several minutes)...")
        saved_path = client.collect_and_download_diagnostic_data(
            output_path=output_path,
            # diagnostic_data_type=None -> vendor default (OEM or Manager)
            timeout=1800,
        )
        print(f"Diagnostic bundle saved to: {saved_path}")

        # --- Manual flow (finer control over each step) ---
        # task = client.collect_diagnostic_data(diagnostic_data_type="Manager")
        # finished = client.wait_for_task(task.id, timeout=1800)
        # data = client.download_diagnostic_data(finished)  # returns bytes
        # print(f"Downloaded {len(data)} bytes")

    except RedfishValidationError as exc:
        # Raised when the BMC does not expose CollectDiagnosticData, or when
        # no artifact URI can be resolved.
        print(f"Validation error: {exc}")
    except RedfishException as exc:
        print(f"Redfish error: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
