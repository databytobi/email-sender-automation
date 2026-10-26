"""Classic SMTP delivery backend (default).

Wraps the existing smtplib logic in sender.py — one authenticated,
STARTTLS-secured connection reused for the whole campaign.
"""

import smtplib

from logger import logger
from providers.base import (
    AuthDeliveryError,
    DeliveryProvider,
    RetryableDeliveryError,
)
from sender import SMTPAuthError, connect_smtp, send_email


class SMTPProvider(DeliveryProvider):
    name = "smtp"
    supports_bounce_sync = False

    def __init__(self):
        self._smtp = None

    def connect(self):
        try:
            self._smtp = connect_smtp()
        except SMTPAuthError as error:
            raise AuthDeliveryError(str(error)) from error

    def send(self, payload):
        try:
            result = send_email(
                self._smtp,
                recipient_email=payload.to_email,
                subject=payload.subject,
                text_body=payload.text_body,
                html_body=payload.html_body,
                attachment_paths=payload.attachment_paths,
                extra_headers=payload.extra_headers,
            )
        except smtplib.SMTPServerDisconnected as error:
            raise RetryableDeliveryError(str(error)) from error

        result.setdefault("message_id", None)
        return result

    def close(self):
        if self._smtp is not None:
            try:
                self._smtp.quit()
            except Exception:
                logger.warning("Could not close the SMTP connection cleanly.")
            self._smtp = None

    def fetch_bounces(self):
        # Plain SMTP has no bounce API: bounces arrive as emails in the
        # sender's inbox. Use the Gmail backend's --sync-bounces if the
        # sender is a Gmail account, or --import-bounces from a CSV.
        logger.info(
            "The SMTP backend cannot sync bounces automatically. Use "
            "'--sync-bounces' with the gmail backend, or import a bounce "
            "CSV with '--import-bounces FILE'."
        )
        return []
