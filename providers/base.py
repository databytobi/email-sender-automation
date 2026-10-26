from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EmailPayload:
    """Provider-neutral description of one outgoing email.

    Every delivery backend (SMTP, Gmail API, SendGrid, SES) translates
    this into its own native format, so the campaign loop never has
    to care which backend is active.
    """

    to_email: str
    subject: str
    text_body: str
    html_body: str = ""
    attachment_paths: list = field(default_factory=list)
    extra_headers: dict = field(default_factory=dict)
    custom_args: dict = field(default_factory=dict)


class AuthDeliveryError(Exception):
    """Raised when the backend rejects our identity or credentials.

    The campaign is aborted when this happens: retrying with broken
    credentials is pointless and can trigger provider lockouts.
    """


class RetryableDeliveryError(Exception):
    """Raised when the connection dropped but a retry may succeed.

    The caller should reconnect once and resend the same payload.
    """


class ProviderNotInstalledError(ImportError):
    """Raised when the selected backend's optional dependency is missing.

    The message tells the user exactly which package to install.
    """


class DeliveryProvider(ABC):
    """Interface implemented by every delivery backend."""

    #: Backend name as selected via DELIVERY_BACKEND / --backend.
    name = "base"

    #: Whether fetch_bounces() can pull bounce data from the provider.
    supports_bounce_sync = False

    @abstractmethod
    def connect(self):
        """Authenticate / open a session. Raise AuthDeliveryError on bad credentials."""

    @abstractmethod
    def send(self, payload):
        """Send one EmailPayload.

        Returns:
            dict: {"success": bool, "error": str | None, "message_id": str | None}
        """

    def reconnect(self):
        """Re-establish a session after a RetryableDeliveryError."""
        self.close()
        self.connect()

    def close(self):
        """Release the session. Never raises."""

    def fetch_bounces(self):
        """Return a list of bounce dicts: [{"email", "reason", "date"}].

        Backends without a bounce API return an empty list.
        """
        return []
