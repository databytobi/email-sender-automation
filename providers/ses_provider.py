"""Amazon SES v2 delivery backend.

Sends via the SES v2 API and can pull the account-level suppression
list for --sync-bounces. For full bounce processing also configure a
configuration set with an SNS/event destination — SES automatically
adds hard bounces to the account suppression list, which is what this
backend reads.

Requires the optional dependency:
    pip install boto3

Note: while your SES account is in sandbox mode, both the sender and
every recipient address must be verified. Request production access
before real campaigns.
"""

from pathlib import Path

from config import AWS_REGION, SES_FROM_ADDRESS
from logger import logger, mask_email
from providers.base import (
    AuthDeliveryError,
    DeliveryProvider,
    ProviderNotInstalledError,
    RetryableDeliveryError,
)


def _import_boto3():
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError as error:
        raise ProviderNotInstalledError(
            "The SES backend requires the 'boto3' package. "
            "Install it with: pip install boto3"
        ) from error

    return boto3, ClientError


def build_ses_send_kwargs(payload):
    """Translate an EmailPayload into sesv2 send_email() kwargs.

    Pure function (no network) so it is unit-testable.
    """
    import mimetypes

    body = {"Text": {"Data": payload.text_body, "Charset": "UTF-8"}}

    if payload.html_body:
        body["Html"] = {"Data": payload.html_body, "Charset": "UTF-8"}

    simple = {
        "Subject": {"Data": payload.subject, "Charset": "UTF-8"},
        "Body": body,
    }

    if payload.extra_headers:
        simple["Headers"] = [
            {"Name": str(name), "Value": str(value)}
            for name, value in payload.extra_headers.items()
        ]

    attachments = []

    for attachment_path in payload.attachment_paths:
        attachment = Path(attachment_path)
        content_type = mimetypes.guess_type(attachment.name)[0] or (
            "application/octet-stream"
        )

        attachments.append(
            {
                "Filename": attachment.name,
                "RawContent": attachment.read_bytes(),
                "ContentType": content_type,
            }
        )

    if attachments:
        simple["Attachments"] = attachments

    return {
        "FromEmailAddress": SES_FROM_ADDRESS,
        "Destination": {"ToAddresses": [payload.to_email]},
        "Content": {"Simple": simple},
    }


class SESProvider(DeliveryProvider):
    name = "ses"
    supports_bounce_sync = True

    def __init__(self):
        self._client = None

    def connect(self):
        boto3, _ = _import_boto3()

        self._client = boto3.client("sesv2", region_name=AWS_REGION)

        # Fail fast on bad credentials instead of one failure per recipient.
        try:
            self._client.get_account()
        except Exception as error:
            self._client = None
            raise AuthDeliveryError(
                f"AWS SES rejected the credentials or region "
                f"({AWS_REGION}): {error}"
            ) from error

    def send(self, payload):
        if self._client is None:
            raise RuntimeError("SESProvider.send() called before connect()")

        boto3, ClientError = _import_boto3()

        try:
            response = self._client.send_email(**build_ses_send_kwargs(payload))
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            message = error.response.get("Error", {}).get("Message", str(error))

            if code in ("Throttling", "RequestThrottled", "TooManyRequestsException"):
                raise RetryableDeliveryError(f"SES throttling: {message}") from error

            if code in ("InvalidClientTokenId", "UnrecognizedClientException",
                        "SignatureDoesNotMatch", "AccessDeniedException"):
                raise AuthDeliveryError(f"SES auth error: {message}") from error

            logger.error(
                f"SES refused mail to {mask_email(payload.to_email)} "
                f"({code}): {message}"
            )
            return {
                "success": False,
                "error": f"SES {code}: {message}",
                "message_id": None,
            }
        except (ConnectionError, TimeoutError) as error:
            raise RetryableDeliveryError(
                f"SES connection error: {error}"
            ) from error

        message_id = response.get("MessageId")

        logger.info(f"Email sent via SES to {mask_email(payload.to_email)}")

        return {
            "success": True,
            "error": None,
            "message_id": message_id,
        }

    def close(self):
        self._client = None

    def fetch_bounces(self):
        """Pull the account-level suppression list (bounces + complaints)."""
        if self._client is None:
            self.connect()

        bounces = []
        paginator = self._client.get_paginator("list_suppressed_destinations")

        for page in paginator.paginate():
            for item in page.get("SuppressedDestinations", []):
                bounces.append(
                    {
                        "email": item.get("EmailAddress", ""),
                        "reason": f"SES suppression: {item.get('Reason', 'unknown')}",
                        "date": item.get("LastUpdateTime", ""),
                    }
                )

        return bounces
