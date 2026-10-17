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


if __name__ == "__main__":
    unittest.main()
