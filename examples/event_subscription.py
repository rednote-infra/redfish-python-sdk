"""
Event subscription example — full CRUD loop for Redfish event subscriptions.

This example demonstrates the typical workflow used by an event-relay
service that needs to make sure exactly one subscription exists on a BMC
pointing at its own callback URL:

    1. List all existing subscriptions on the BMC.
    2. For each one, GET its detail and compare ``Destination`` against
       the expected callback URL.
       - If it does not match, DELETE it so we don't leave stale entries.
    3. If no matching subscription was found, CREATE a new one.
       BMCs from different vendors accept noticeably different payload
       shapes for the same logical "subscribe" operation, so the example
       tries multiple payload variants in order and keeps the first one
       the BMC accepts. The SDK itself ships no vendor defaults; the
       caller decides which payloads to try.

Environment variables:
    BMC_IP, BMC_USER, BMC_PASSWORD  — BMC connection info.
    CALLBACK_URL                    — URL the BMC should POST events to.
    CALLBACK_CONTEXT                — Optional context string (default: "RedfishEventRelay").
"""
import os
from typing import Any, Dict, List, Optional

from redfish_sdk import RedfishClient, RedfishException


def reconcile_subscriptions(
    client: RedfishClient,
    expected_destination: str,
) -> Optional[str]:
    """
    Walk the Subscriptions collection, deleting any subscription whose
    Destination does not match ``expected_destination``.

    Returns:
        The ``@odata.id`` of the surviving (matching) subscription if one
        exists, otherwise ``None``.
    """
    matched_odata_id: Optional[str] = None

    for sub in client.get_subscriptions():
        odata_id = sub.odata_id
        if not odata_id:
            # Collection enumeration should always populate @odata.id, but
            # if a BMC returns a malformed entry just skip it.
            continue

        # Re-GET the detail in case the collection-expansion was partial.
        try:
            detail = client.get_subscription(odata_id)
        except RedfishException as exc:
            print(f"[warn] failed to GET {odata_id}: {exc} — skipping")
            continue

        if detail.destination == expected_destination:
            print(f"[keep] {odata_id} already points at {expected_destination}")
            matched_odata_id = odata_id
            continue

        print(
            f"[delete] {odata_id} -> {detail.destination!r} "
            f"does not match expected {expected_destination!r}"
        )
        try:
            client.delete_subscription(odata_id)
        except RedfishException as exc:
            print(f"[warn] delete {odata_id} failed: {exc}")

    return matched_odata_id


def try_subscribe(
    client: RedfishClient,
    payloads: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Try each payload in order, returning the ``@odata.id`` of the first
    subscription the BMC accepts. Returns ``None`` if every payload was
    rejected.

    Each payload is sent as ``raw_body`` so the caller has full control
    over the request shape, including any OEM-specific fields.
    """
    for idx, payload in enumerate(payloads, start=1):
        print(f"[try] payload #{idx}: {payload}")
        try:
            created = client.subscribe(
                destination=payload["Destination"],
                raw_body=payload,
            )
        except RedfishException as exc:
            print(f"[try] payload #{idx} rejected: {exc}")
            continue

        print(f"[ok]  payload #{idx} accepted -> {created.odata_id}")
        return created.odata_id

    return None


def main() -> None:
    bmc_ip = os.environ["BMC_IP"]
    bmc_user = os.environ["BMC_USER"]
    bmc_password = os.environ["BMC_PASSWORD"]
    callback_url = os.environ["CALLBACK_URL"]
    callback_context = os.environ.get("CALLBACK_CONTEXT", "RedfishEventRelay")

    client = RedfishClient(
        host=bmc_ip,
        username=bmc_user,
        password=bmc_password,
        verify_ssl=False,
    )

    try:
        # --- step 1 & 2: list + reconcile -----------------------------
        existing = reconcile_subscriptions(client, callback_url)
        if existing is not None:
            print(f"Already subscribed at {existing}; nothing to do.")
            return

        # --- step 3: try creating with progressively richer payloads --
        #
        # Different BMCs accept different fields. We declare a handful of
        # payload variants here and let `try_subscribe` walk them in
        # order; the first one the BMC accepts wins. Adjust / extend
        # this list to match the BMCs you actually deploy against.
        payloads: List[Dict[str, Any]] = [
            # Payload A: minimal — destination + protocol + a single event type.
            {
                "Destination": callback_url,
                "Protocol": "Redfish",
                "EventTypes": ["Alert"],
                "Context": callback_context,
            },
            # Payload B: scoped via OriginResources — some BMCs reject the
            # request unless an origin resource list is supplied.
            {
                "Destination": callback_url,
                "Protocol": "Redfish",
                "EventTypes": ["Alert"],
                "Context": callback_context,
                "OriginResources": [{"@odata.id": "/redfish/v1/Systems"}],
            },
            # Payload C: full DSP0266-style payload with SubscriptionType,
            # registry prefixes, message ids and a retry policy. Use this
            # when a BMC requires the newer EventService fields.
            {
                "Destination": callback_url,
                "Protocol": "Redfish",
                "Context": callback_context,
                "SubscriptionType": "RedfishEvent",
                "EventFormatType": "Event",
                "RegistryPrefixes": [],
                "MessageIds": [],
                "DeliveryRetryPolicy": "SuspendRetries",
                "HttpHeaders": [],
            },
        ]

        created_id = try_subscribe(client, payloads)
        if created_id is None:
            print("All subscribe attempts failed; giving up.")
            return

        # Optional: re-GET the new subscription to verify it stuck.
        new_sub = client.get_subscription(created_id)
        print(
            f"Subscription created: id={new_sub.id} "
            f"destination={new_sub.destination} context={new_sub.context}"
        )

    except RedfishException as exc:
        print(f"Redfish error: {exc}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
