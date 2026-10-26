"""Bounce parsing helpers.

Extracts the failed recipient addresses from Delivery Status
Notifications (DSNs) — the "mailer-daemon" emails a provider sends
when a message cannot be delivered.
"""

import base64
import re

FINAL_RECIPIENT_RE = re.compile(
    r"final-recipient:\s*rfc822\s*;\s*(?P<address>\S+@\S+)",
    re.IGNORECASE,
)

FAILED_ACTION_RE = re.compile(r"action:\s*failed", re.IGNORECASE)


def _decode_part_data(data):
    """Decode a Gmail API body payload (base64url, no padding)."""
    if not data:
        return ""

    padding = "=" * (-len(data) % 4)

    try:
        return base64.urlsafe_b64decode(data + padding).decode(
            "utf-8", errors="replace"
        )
    except Exception:
        return ""


def _headers_dict(headers):
    """Convert a Gmail API headers list [{name, value}] into a dict."""
    return {
        header["name"].lower(): header["value"]
        for header in headers or []
        if "name" in header
    }


def _walk_delivery_status_parts(part):
    """Yield delivery-status headers/decoded text from a MIME subtree."""
    if not part:
        return

    mime_type = part.get("mimeType", "")
    headers = part.get("headers", [])

    if mime_type == "message/delivery-status":
        # The DSN headers live as header fields of the delivery-status
        # part (Final-Recipient, Action, ...).
        text = "\n".join(
            f"{header.get('name', '')}: {header.get('value', '')}"
            for header in headers
        )
        text += "\n" + _decode_part_data(part.get("body", {}).get("data", ""))
        yield text

    for child in part.get("parts", []):
        yield from _walk_delivery_status_parts(child)


def parse_gmail_bounce(message):
    """Extract failed recipient addresses from a Gmail bounce message.

    Handles both:
    - the X-Failed-Recipients header (Google's bounce format), and
    - RFC 3464 message/delivery-status parts with
      "Final-Recipient: rfc822; addr" + "Action: failed".

    Args:
        message: The Gmail API message resource (format="full").

    Returns:
        list[str]: Failed recipient addresses (empty if none found).
    """
    payload = message.get("payload", {})
    headers = _headers_dict(payload.get("headers", []))

    addresses = set()

    # Google's DSNs carry the failed address in X-Failed-Recipients.
    failed_header = headers.get("x-failed-recipients", "")

    for address in failed_header.split(","):
        address = address.strip()

        if "@" in address:
            addresses.add(address)

    # Standard DSNs carry it inside message/delivery-status parts.
    for dsn_text in _walk_delivery_status_parts(payload):
        if FINAL_RECIPIENT_RE.search(dsn_text):
            for match in FINAL_RECIPIENT_RE.finditer(dsn_text):
                addresses.add(match.group("address").strip())

    return sorted(addresses)
