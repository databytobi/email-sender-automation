"""SendGrid delivery backend (v3 REST API).

Sends through https://api.sendgrid.com/v3/mail/send and can pull the
account's bounce list for --sync-bounces.

Requires the optional dependency: pip install requests
"""

import base64
import mimetypes
from pathlib import Path

from config import EMAIL_ADDRESS, SENDGRID_API_KEY, SENDER_NAME
from logger import logger, mask_email
from providers.base import (
    AuthDeliveryError,
    DeliveryProvider,
    ProviderNotInstalledError,
    RetryableDeliveryError,
)

API_BASE = "https://api.sendgrid.com/v3"


def _import_requests():
    try:
        import requests
    except ImportError as error:
        raise ProviderNotInstalledError(
            "The SendGrid backend requires the 'requests' package. "
            "Install it with: pip install requests"
        ) from error

    return requests


def build_sendgrid_payload(payload):
    """Translate an EmailPayload into a SendGrid v3 mail/send body.

    Pure function (no network) so it is unit-testable.
    """
    body = {
        "personalizations": [
            {
                "to": [{"email": payload.to_email}],
                "custom_args": {
                    key: str(value)
                    for key, value in payload.custom_args.items()
                },
            }
        ],
        "from": {
            "email": EMAIL_ADDRESS,
            "name": SENDER_NAME,
        },
        "subject": payload.subject,
        "content": [
            {
                "type": "text/plain",
                "value": payload.text_body,
            }
        ],
    }

    if payload.html_body:
        body["content"].append(
            {
                "type": "text/html",
                "value": payload.html_body,
            }
        )

    if payload.extra_headers:
        body["headers"] = dict(payload.extra_headers)

    attachments = []

    for attachment_path in payload.attachment_paths:
        attachment = Path(attachment_path)

        content_type = mimetypes.guess_type(attachment.name)[0] or (
            "application/octet-stream"
        )

        attachments.append(
            {
                "content": base64.b64encode(attachment.read_bytes()).decode(
                    "ascii"
                ),
                "filename": attachment.name,
                "type": content_type,
                "disposition": "attachment",
            }
        )

    if attachments:
        body["attachments"] = attachments

    return body


class SendGridProvider(DeliveryProvider):
    name = "sendgrid"
    supports_bounce_sync = True

    def __init__(self):
        self._session = None
        self._requests = None

    def connect(self):
        requests = _import_requests()
        self._requests = requests

        # Fail fast on a bad API key instead of one failure per recipient.
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json",
            }
        )

        response = session.get(f"{API_BASE}/scopes")

        if response.status_code in (401, 403):
            raise AuthDeliveryError(
                "SendGrid rejected the API key. Check SENDGRID_API_KEY."
            )

        if response.status_code == 429:
            raise RetryableDeliveryError("SendGrid rate limit hit at connect")

        if response.status_code >= 500:
            raise RetryableDeliveryError(
                f"SendGrid unavailable (HTTP {response.status_code})"
            )

        self._session = session

    def send(self, payload):
        if self._session is None:
            raise RuntimeError("SendGridProvider.send() called before connect()")

        try:
            response = self._session.post(
                f"{API_BASE}/mail/send",
                json=build_sendgrid_payload(payload),
                timeout=30,
            )
        except self._requests.exceptions.RequestException as error:
            raise RetryableDeliveryError(
                f"SendGrid connection error: {error}"
            ) from error

        if response.status_code == 202:
            logger.info(f"Email accepted by SendGrid for {mask_email(payload.to_email)}")
            return {
                "success": True,
                "error": None,
                "message_id": response.headers.get("X-Message-Id"),
            }

        if response.status_code == 429:
            raise RetryableDeliveryError("SendGrid rate limit hit")

        if response.status_code in (500, 502, 503, 504):
            raise RetryableDeliveryError(
                f"SendGrid server error (HTTP {response.status_code})"
            )

        if response.status_code in (401, 403):
            raise AuthDeliveryError(
                "SendGrid rejected the API key. Check SENDGRID_API_KEY."
            )

        # 4xx (other than auth): permanent for this recipient.
        try:
            errors = response.json().get("errors", [])
            detail = "; ".join(
                error.get("message", "") for error in errors
            ) or response.text[:200]
        except ValueError:
            detail = response.text[:200]

        logger.error(
            f"SendGrid refused mail to {mask_email(payload.to_email)} "
            f"(HTTP {response.status_code}): {detail}"
        )

        return {
            "success": False,
            "error": f"SendGrid HTTP {response.status_code}: {detail}",
            "message_id": None,
        }

    def close(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def fetch_bounces(self):
        """Pull the account bounce list (SendGrid suppression/bounces)."""
        if self._session is None:
            self.connect()

        try:
            response = self._session.get(f"{API_BASE}/suppression/bounces")
        except self._requests.exceptions.RequestException as error:
            logger.error(f"Could not reach SendGrid for bounce sync: {error}")
            return []

        if response.status_code != 200:
            logger.error(
                f"Could not fetch SendGrid bounces (HTTP {response.status_code})"
            )
            return []

        bounces = []

        for entry in response.json():
            bounces.append(
                {
                    "email": entry.get("email", ""),
                    "reason": entry.get("reason") or "bounced",
                    "date": entry.get("created") or "",
                }
            )

        return bounces
