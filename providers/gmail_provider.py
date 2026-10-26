"""Gmail API delivery backend (OAuth2).

Sends via users.messages.send and scans the INBOX for Delivery Status
Notifications for --sync-bounces — the same Gmail account that sent the
campaign receives the bounces, so they can be processed automatically.

Requires the optional dependencies:
    pip install google-auth google-auth-oauthlib google-api-python-client
"""

import base64

from bounces import parse_gmail_bounce
from config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE
from logger import logger, mask_email
from providers.base import (
    AuthDeliveryError,
    DeliveryProvider,
    ProviderNotInstalledError,
    RetryableDeliveryError,
)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

BOUNCE_QUERY = "from:mailer-daemon newer_than:30d"
BOUNCE_PAGE_SIZE = 100


def _import_google_libs():
    try:
        import googleapiclient.discovery
        import google_auth_oauthlib.flow
        import google.oauth2.credentials
    except ImportError as error:
        raise ProviderNotInstalledError(
            "The Gmail backend requires the Google API libraries. Install "
            "them with: pip install google-auth google-auth-oauthlib "
            "google-api-python-client"
        ) from error

    return googleapiclient.discovery, google_auth_oauthlib.flow, google.oauth2.credentials


class GmailProvider(DeliveryProvider):
    name = "gmail"
    supports_bounce_sync = True

    def __init__(self):
        self._service = None
        self._account_email = None

    def connect(self):
        discovery, gauth_flow, google_credentials = _import_google_libs()

        credentials = self._load_credentials(google_credentials)

        if credentials is None:
            credentials = self._run_oauth_flow(gauth_flow)

        self._service = discovery.build(
            "gmail", "v1", credentials=credentials, cache_discovery=False
        )

        # Remember the authenticated account: the Gmail API always sends
        # from this address regardless of what .env says.
        profile = self._service.users().getProfile(userId="me").execute()
        self._account_email = profile.get("emailAddress")

    def _load_credentials(self, google_credentials):
        if not GMAIL_TOKEN_FILE.is_file():
            return None

        try:
            credentials = google_credentials.Credentials.from_authorized_user_file(
                str(GMAIL_TOKEN_FILE), SCOPES
            )
        except (ValueError, KeyError):
            return None

        return credentials

    def _run_oauth_flow(self, gauth_flow):
        if not GMAIL_CREDENTIALS_FILE.is_file():
            raise AuthDeliveryError(
                f"Gmail OAuth client file not found: {GMAIL_CREDENTIALS_FILE}. "
                "Download 'client_secret.json' from Google Cloud Console "
                "(APIs & Services > Credentials > OAuth client ID, Desktop app) "
                "and set GMAIL_CREDENTIALS_FILE."
            )

        try:
            flow = gauth_flow.InstalledAppFlow.from_client_secrets_file(
                str(GMAIL_CREDENTIALS_FILE), SCOPES
            )
            credentials = flow.run_local_server(port=0)
        except Exception as error:
            raise AuthDeliveryError(
                f"Gmail OAuth flow failed: {error}"
            ) from error

        # Cache the token so scheduled runs do not need the browser.
        GMAIL_TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")

        return credentials

    def send(self, payload):
        if self._service is None:
            raise RuntimeError("GmailProvider.send() called before connect()")

        # The Gmail API only allows sending from the authenticated
        # account (or its aliases), so force the real account address.
        message = build_gmail_message(
            payload,
            sender_email=self._account_email,
        )

        try:
            sent = (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": message})
                .execute()
            )
        except (ConnectionError, TimeoutError) as error:
            raise RetryableDeliveryError(
                f"Connection to the Gmail API was lost: {error}"
            ) from error
        except Exception as error:
            status = getattr(getattr(error, "resp", None), "status", None)

            if status in (401, 403):
                raise AuthDeliveryError(
                    f"Gmail API rejected the credentials: {error}"
                ) from error

            if status in (429, 500, 502, 503, 504):
                raise RetryableDeliveryError(
                    f"Gmail API transient error (HTTP {status})"
                ) from error

            logger.error(f"Gmail API error for {mask_email(payload.to_email)}: {error}")
            return {
                "success": False,
                "error": str(error),
                "message_id": None,
            }

        logger.info(f"Email sent via Gmail API to {mask_email(payload.to_email)}")

        return {
            "success": True,
            "error": None,
            "message_id": sent.get("id"),
        }

    def fetch_bounces(self):
        """Scan the INBOX for recent Delivery Status Notifications."""
        if self._service is None:
            self.connect()

        response = (
            self._service.users()
            .messages()
            .list(userId="me", q=BOUNCE_QUERY, maxResults=BOUNCE_PAGE_SIZE)
            .execute()
        )

        bounces = []
        seen = set()

        for message_summary in response.get("messages", []):
            message = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_summary["id"], format="full")
                .execute()
            )

            for address in parse_gmail_bounce(message):
                key = address.lower()

                if key not in seen:
                    seen.add(key)
                    bounces.append(
                        {
                            "email": address,
                            "reason": "Delivery Status Notification (bounce)",
                            "date": "",
                        }
                    )

        return bounces

    def close(self):
        self._service = None


def build_gmail_message(payload, sender_email):
    """Serialize an EmailPayload as a base64url MIME message.

    Pure function (no network) so it is unit-testable.
    """
    from sender import build_email_message

    message = build_email_message(
        payload.to_email,
        payload.subject,
        text_body=payload.text_body,
        html_body=payload.html_body,
        attachment_paths=payload.attachment_paths,
        extra_headers=payload.extra_headers,
        sender_email=sender_email,
    )

    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
