"""Unsubscribe support: stateless tokens, footers, and headers.

Design:
- Each recipient gets an HMAC-signed unsubscribe token
  (token = HMAC-SHA256(secret, email)). No database is needed to
  verify a click later — the same secret regenerates/verifies it.
- An HTTPS unsubscribe endpoint (see unsubscribe_server.py) enables
  RFC 8058 one-click unsubscribe. A mailto: fallback works without
  any hosting.
- Every campaign email gets a footer plus the List-Unsubscribe and
  List-Unsubscribe-Post headers, which Gmail and other providers
  surface as a native "Unsubscribe" button.
"""

import hashlib
import hmac
import urllib.parse

HTML_FOOTER = (
    '<hr style="border:none;border-top:1px solid #ddd;">'
    '<p style="color:gray;font-size:12px;">'
    "You are receiving this email because you are on our recipient list."
    ' <a href="{link}" style="color:#2563eb;">Unsubscribe</a>'
    "</p>"
)

TEXT_FOOTER = (
    "\n\n--\n"
    "You are receiving this email because you are on our recipient list.\n"
    "Unsubscribe: {link}\n"
)

MAILTO_FOOTER = (
    "\n\n--\n"
    "You are receiving this email because you are on our recipient list.\n"
    "To unsubscribe, reply with 'unsubscribe' or send an empty email to:\n"
    "{link}\n"
)


def generate_token(email, secret):
    """Generate a stable, stateless unsubscribe token for an address."""
    return hmac.new(
        secret.encode("utf-8"),
        email.lower().strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


def verify_token(email, token, secret):
    """Verify an unsubscribe token (constant-time)."""
    expected = generate_token(email, secret)
    return hmac.compare_digest(expected, str(token or "").lower())


def build_unsubscribe_link(email, base_url, secret):
    """Build the HTTPS unsubscribe link for a recipient."""
    query = urllib.parse.urlencode({"email": email, "token": generate_token(email, secret)})
    return f"{base_url.rstrip('/')}/unsubscribe?{query}"


def build_mailto_link(email, mailto_address, secret):
    """Build the mailto: unsubscribe link for a recipient.

    The token goes in the subject so replying needs no manual step.
    """
    subject = urllib.parse.quote(f"unsubscribe-{email}")
    return f"mailto:{mailto_address}?subject={subject}"


def build_unsubscribe_headers(https_link=None, mailto_link=None):
    """Build the List-Unsubscribe / List-Unsubscribe-Post headers.

    One-click unsubscribe (RFC 8058) requires an HTTPS link.
    """
    targets = []

    if https_link:
        targets.append(f"<{https_link}>")

    if mailto_link:
        targets.append(f"<{mailto_link}>")

    if not targets:
        return {}

    headers = {"List-Unsubscribe": ", ".join(targets)}

    if https_link:
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    return headers


def append_footer(text_body, html_body, https_link=None, mailto_link=None):
    """Append the unsubscribe footer to both bodies.

    Returns:
        tuple: (text_body, html_body) with the footer appended.
    """
    if https_link:
        text_body = text_body + TEXT_FOOTER.format(link=https_link)
    elif mailto_link:
        text_body = text_body + MAILTO_FOOTER.format(link=mailto_link)

    if html_body:
        link = https_link or mailto_link or "#"
        html_body = html_body + HTML_FOOTER.format(link=link)

    return text_body, html_body
