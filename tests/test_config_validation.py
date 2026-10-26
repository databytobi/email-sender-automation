import unittest
from unittest import mock

import config


class ValidateConfigurationTests(unittest.TestCase):
    def test_unknown_email_type_raises_with_valid_options(self):
        with self.assertRaises(ValueError) as context:
            config.validate_configuration(email_type="bogus")

        self.assertIn("welcome", str(context.exception))
        self.assertIn("newsletter", str(context.exception))

    def test_only_the_selected_campaign_is_validated(self):
        # Break a campaign that is NOT selected: it must not block the run.
        original = config.EMAIL_CONFIG["newsletter"]["text_template"]

        try:
            config.EMAIL_CONFIG["newsletter"]["text_template"] = (
                original.parent / "does-not-exist.txt"
            )
            # welcome has all files present, so this must not raise.
            config.validate_configuration(
                email_type="welcome", check_credentials=False
            )
        finally:
            config.EMAIL_CONFIG["newsletter"]["text_template"] = original

    def test_selected_campaign_with_missing_template_raises(self):
        original = config.EMAIL_CONFIG["welcome"]["text_template"]

        try:
            config.EMAIL_CONFIG["welcome"]["text_template"] = (
                original.parent / "does-not-exist.txt"
            )

            with self.assertRaises(ValueError):
                config.validate_configuration(
                    email_type="welcome", check_credentials=False
                )
        finally:
            config.EMAIL_CONFIG["welcome"]["text_template"] = original

    def test_credentials_are_required_for_live_runs(self):
        with mock.patch.object(config, "EMAIL_ADDRESS", None):
            with self.assertRaises(ValueError) as context:
                config.validate_configuration(
                    email_type="welcome", check_credentials=True
                )

            self.assertIn("EMAIL_ADDRESS", str(context.exception))

    def test_credentials_are_not_required_for_dry_runs(self):
        with mock.patch.object(config, "EMAIL_ADDRESS", None), \
             mock.patch.object(config, "EMAIL_PASSWORD", None):
            # Templates and subjects for the welcome campaign exist, so
            # a dry run validates fine without credentials.
            config.validate_configuration(
                email_type="welcome", check_credentials=False
            )

    def test_invalid_smtp_port_is_rejected(self):
        with mock.patch.object(config, "SMTP_PORT", None):
            with self.assertRaises(ValueError) as context:
                config.validate_configuration(
                    email_type="welcome", check_credentials=True
                )

            self.assertIn("SMTP_PORT", str(context.exception))


class BackendValidationTests(unittest.TestCase):
    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(ValueError) as context:
            config.validate_configuration(
                email_type="welcome", check_credentials=False, backend="pigeon"
            )

        self.assertIn("smtp", str(context.exception))
        self.assertIn("sendgrid", str(context.exception))

    def test_sendgrid_backend_requires_api_key(self):
        with mock.patch.object(config, "SENDGRID_API_KEY", None), \
             mock.patch.object(config, "EMAIL_ADDRESS", None):
            with self.assertRaises(ValueError) as context:
                config.validate_configuration(
                    email_type="welcome",
                    check_credentials=True,
                    backend="sendgrid",
                )

        self.assertIn("SENDGRID_API_KEY", str(context.exception))

    def test_gmail_backend_requires_credentials_file(self):
        with mock.patch.object(config, "GMAIL_CREDENTIALS_FILE",
                               config.BASE_DIR / "does-not-exist.json"):
            with self.assertRaises(ValueError) as context:
                config.validate_configuration(
                    email_type="welcome",
                    check_credentials=True,
                    backend="gmail",
                )

        self.assertIn("GMAIL_CREDENTIALS_FILE", str(context.exception))

    def test_ses_backend_requires_from_address(self):
        with mock.patch.object(config, "SES_FROM_ADDRESS", None):
            with self.assertRaises(ValueError) as context:
                config.validate_configuration(
                    email_type="welcome",
                    check_credentials=True,
                    backend="ses",
                )

        self.assertIn("SES_FROM_ADDRESS", str(context.exception))

    def test_dry_run_skips_all_credential_checks_for_any_backend(self):
        # Even with zero credentials configured, a dry run must work —
        # it only renders emails.
        with mock.patch.object(config, "EMAIL_ADDRESS", None), \
             mock.patch.object(config, "EMAIL_PASSWORD", None), \
             mock.patch.object(config, "SENDGRID_API_KEY", None), \
             mock.patch.object(config, "SES_FROM_ADDRESS", None):
            for backend in config.VALID_BACKENDS:
                with self.subTest(backend=backend):
                    config.validate_configuration(
                        email_type="welcome",
                        check_credentials=False,
                        backend=backend,
                    )


class UnsubscribeSettingsTests(unittest.TestCase):
    def test_disabled_without_secret(self):
        with mock.patch.object(config, "UNSUBSCRIBE_SECRET", ""), \
             mock.patch.object(config, "UNSUBSCRIBE_BASE_URL", "https://x.com"), \
             mock.patch.object(config, "UNSUBSCRIBE_MAILTO", "u@x.com"):
            self.assertIsNone(config.unsubscribe_settings())

    def test_disabled_without_any_target(self):
        with mock.patch.object(config, "UNSUBSCRIBE_SECRET", "s3cret"), \
             mock.patch.object(config, "UNSUBSCRIBE_BASE_URL", ""), \
             mock.patch.object(config, "UNSUBSCRIBE_MAILTO", ""):
            self.assertIsNone(config.unsubscribe_settings())

    def test_enabled_with_secret_and_mailto(self):
        with mock.patch.object(config, "UNSUBSCRIBE_SECRET", "s3cret"), \
             mock.patch.object(config, "UNSUBSCRIBE_BASE_URL", ""), \
             mock.patch.object(config, "UNSUBSCRIBE_MAILTO", "unsub@x.com"):
            settings = config.unsubscribe_settings()

        self.assertEqual(settings["mailto"], "unsub@x.com")
        self.assertEqual(settings["secret"], "s3cret")


if __name__ == "__main__":
    unittest.main()
