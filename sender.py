import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from config import (
    EMAIL_ADDRESS,
    EMAIL_PASSWORD,
    SENDER_NAME,
    SMTP_PORT,
    SMTP_SERVER,
)

from logger import logger, mask_email


class SMTPAuthError(Exception):
    """Raised when the SMTP server rejects the configured credentials.

    The caller must abort the whole campaign when this happens:
    retrying the remaining recipients with broken credentials is
    pointless and can trigger provider lockouts.
    """


def connect_smtp(timeout=30):
    """Open, secure, and authenticate a single SMTP connection.

    The connection is meant to be reused for every recipient of a
    campaign instead of reconnecting per email.

    Returns:
        smtplib.SMTP: A logged-in connection ready to send mail.

    Raises:
        SMTPAuthError: If the server rejects the credentials.
        smtplib.SMTPException: If the connection or TLS handshake fails.
    """
    smtp = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=timeout)
    smtp.starttls(context=ssl.create_default_context())

    try:
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    except smtplib.SMTPAuthenticationError as error:
        smtp.quit()
        raise SMTPAuthError(
            "Authentication failed. Check EMAIL_ADDRESS / EMAIL_PASSWORD "
            "(for Gmail, use an app password: "
            "https://support.google.com/accounts/answer/185833)."
        ) from error

    return smtp


def _clean_header(value):
    """Remove characters that could break or inject mail headers."""
    return str(value).replace("\r", " ").replace("\n", " ")


def _is_valid_email(recipient_email):
    """Basic sanity check on a recipient address."""
    parsed = parseaddr(str(recipient_email))[1]
    local, separator, domain = parsed.partition("@")
    return (
        parsed == recipient_email
        and bool(local)
        and bool(separator)
        and bool(domain)
    )


def send_email(
    smtp,
    recipient_email,
    subject,
    text_body,
    html_body=None,
    attachment_paths=None,
):
    """Send one email over an existing, authenticated SMTP connection.

    Note:
        smtplib.SMTPServerDisconnected is deliberately re-raised so the
        caller can reconnect and retry the recipient instead of marking
        it as permanently failed.
    """
    try:
        if not _is_valid_email(recipient_email):
            logger.warning(
                f"Skipping invalid email address: {mask_email(recipient_email)}"
            )

            return {
                "success": False,
                "error": "Invalid email address",
            }

        message = EmailMessage()

        message["From"] = f"{_clean_header(SENDER_NAME)} <{EMAIL_ADDRESS}>"
        message["To"] = recipient_email
        message["Subject"] = _clean_header(subject)

        # Plain-text version
        message.set_content(text_body)

        # HTML version
        if html_body:
            message.add_alternative(
                html_body,
                subtype="html",
            )

        # Multiple attachments
        if attachment_paths:
            for attachment_path in attachment_paths:

                attachment = Path(attachment_path)

                if not attachment.is_file():
                    raise FileNotFoundError(
                        f"{attachment} does not exist."
                    )

                # Real MIME type instead of a generic octet-stream, so
                # PDFs are recognized and previewed by mail clients.
                maintype, subtype = (
                    mimetypes.guess_type(attachment.name)[0]
                    or "application/octet-stream"
                ).split("/", 1)

                with attachment.open("rb") as file:
                    message.add_attachment(
                        file.read(),
                        maintype=maintype,
                        subtype=subtype,
                        filename=attachment.name,
                    )

        smtp.send_message(message)

        logger.info(f"Email successfully sent to {mask_email(recipient_email)}")

        return {
            "success": True,
            "error": None,
        }

    except FileNotFoundError as error:
        logger.error(f"Attachment not found: {error}")

        return {
            "success": False,
            "error": str(error),
        }

    except smtplib.SMTPRecipientsRefused:
        logger.error(
            f"Recipient email address was refused: {mask_email(recipient_email)}"
        )

        return {
            "success": False,
            "error": "Recipient refused",
        }

    except smtplib.SMTPServerDisconnected:
        logger.error("Lost connection to the SMTP server.")
        raise

    except smtplib.SMTPException as error:
        logger.error(f"SMTP error: {error}")

        return {
            "success": False,
            "error": str(error),
        }

    except Exception as error:
        logger.exception(
            f"Unexpected error while sending email to {mask_email(recipient_email)}"
        )

        return {
            "success": False,
            "error": str(error),
        }
