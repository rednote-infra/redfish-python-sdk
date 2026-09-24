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
        system = client.get_system()
        chassis = client.get_chassis()
        manager = client.get_manager()
        print('systems', system)
        print('chassis', chassis)
        print('manager', manager)
        print('test done')

    except RedfishException as exc:
        print(f"\nRedfish error: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
