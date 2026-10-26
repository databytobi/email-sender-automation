import unittest

from providers import create_delivery_provider
from providers.base import (
    AuthDeliveryError,
    DeliveryProvider,
    RetryableDeliveryError,
)
from providers.gmail_provider import GmailProvider
from providers.sendgrid_provider import SendGridProvider
from providers.ses_provider import SESProvider
from providers.smtp_provider import SMTPProvider


class ProviderFactoryTests(unittest.TestCase):
    def test_all_backends_map_to_provider_classes(self):
        expected = {
            "smtp": SMTPProvider,
            "gmail": GmailProvider,
            "sendgrid": SendGridProvider,
            "ses": SESProvider,
        }

        for backend, provider_class in expected.items():
            provider = create_delivery_provider(backend)

            self.assertIsInstance(provider, provider_class)
            self.assertIsInstance(provider, DeliveryProvider)
            self.assertEqual(provider.name, backend)

    def test_unknown_backend_raises_with_valid_options(self):
        with self.assertRaises(ValueError) as context:
            create_delivery_provider("carrier-pigeon")

        self.assertIn("smtp", str(context.exception))
        self.assertIn("sendgrid", str(context.exception))


class ProviderInterfaceTests(unittest.TestCase):
    def test_bounce_sync_capability_flags(self):
        self.assertFalse(SMTPProvider().supports_bounce_sync)
        self.assertTrue(GmailProvider().supports_bounce_sync)
        self.assertTrue(SendGridProvider().supports_bounce_sync)
        self.assertTrue(SESProvider().supports_bounce_sync)

    def test_error_hierarchy(self):
        # Both are plain distinct exceptions the campaign loop can catch.
        self.assertNotIsInstance(AuthDeliveryError("x"), RetryableDeliveryError)
        self.assertNotIsInstance(RetryableDeliveryError("x"), AuthDeliveryError)

    def test_reconnect_closes_then_connects(self):
        provider = SMTPProvider()
        calls = []
        provider.close = lambda: calls.append("close")
        provider.connect = lambda: calls.append("connect")

        provider.reconnect()

        self.assertEqual(calls, ["close", "connect"])


if __name__ == "__main__":
    unittest.main()
