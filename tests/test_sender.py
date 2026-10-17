import smtplib
import tempfile
import unittest
from pathlib import Path

from sender import send_email


class FakeSMTP:
    """Minimal SMTP double recording sent messages."""

    def __init__(self):
        self.sent = []
        self.fail_with = None

    def send_message(self, message):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(message)


class SendEmailTests(unittest.TestCase):
    def setUp(self):
        self.smtp = FakeSMTP()

    def _send(self, **overrides):
        kwargs = dict(
            recipient_email="alice@example.com",
            subject="Hello",
            text_body="Hi Alice",
            html_body="<p>Hi Alice</p>",
            attachment_paths=None,
        )
        kwargs.update(overrides)
        return send_email(self.smtp, **kwargs), self.smtp

    def test_successful_send_builds_correct_message(self):
        result, smtp = self._send()

        self.assertTrue(result["success"])
        self.assertIsNone(result["error"])
        self.assertEqual(len(smtp.sent), 1)

        message = smtp.sent[0]
        self.assertEqual(message["To"], "alice@example.com")
        self.assertEqual(message["Subject"], "Hello")

        raw_message = str(message)
        self.assertIn("Hi Alice", raw_message)
        self.assertIn("<p>Hi Alice</p>", raw_message)

    def test_invalid_email_is_rejected_without_sending(self):
        result, smtp = self._send(recipient_email="not-an-email")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Invalid email address")
        self.assertEqual(smtp.sent, [])

    def test_recipient_refused_is_reported_as_failure(self):
        self.smtp.fail_with = smtplib.SMTPRecipientsRefused("nope")

        result, _ = self._send()

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Recipient refused")

    def test_disconnected_connection_is_reraised_for_reconnect(self):
        self.smtp.fail_with = smtplib.SMTPServerDisconnected()

        with self.assertRaises(smtplib.SMTPServerDisconnected):
            self._send()

    def test_attachment_uses_real_mime_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "document.pdf"
            pdf.write_bytes(b"%PDF-1.4 fake content")

            result, smtp = self._send(attachment_paths=[pdf])

            self.assertTrue(result["success"])

            attachments = list(smtp.sent[0].iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(
                attachments[0].get_content_type(), "application/pdf"
            )
            self.assertEqual(attachments[0].get_filename(), "document.pdf")

    def test_missing_attachment_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.pdf"

            result, _ = self._send(attachment_paths=[missing])

            self.assertFalse(result["success"])

    def test_header_injection_is_neutralized(self):
        result, smtp = self._send(subject="Hi\r\nBcc: evil@example.com")

        self.assertTrue(result["success"])
        self.assertNotIn("\r\nBcc", str(smtp.sent[0]))


if __name__ == "__main__":
    unittest.main()
