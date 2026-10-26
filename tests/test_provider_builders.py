import base64
import tempfile
import unittest
from email import message_from_bytes
from pathlib import Path
from unittest import mock

from providers.base import EmailPayload


def _payload(**overrides):
    values = dict(
        to_email="alice@example.com",
        subject="Hello",
        text_body="Hi",
        html_body="<p>Hi</p>",
        attachment_paths=[],
        extra_headers={"List-Unsubscribe": "<mailto:unsub@x.com>"},
        custom_args={"campaign": "welcome"},
    )
    values.update(overrides)
    return EmailPayload(**values)


class SendGridPayloadTests(unittest.TestCase):
    def test_payload_structure(self):
        import providers.sendgrid_provider as sendgrid_provider

        with mock.patch.object(sendgrid_provider, "EMAIL_ADDRESS", "from@example.com"), \
             mock.patch.object(sendgrid_provider, "SENDER_NAME", "Test Sender"):
            body = sendgrid_provider.build_sendgrid_payload(_payload())

        self.assertEqual(
            body["personalizations"][0]["to"][0]["email"], "alice@example.com"
        )
        self.assertEqual(body["from"]["email"], "from@example.com")
        self.assertEqual(body["from"]["name"], "Test Sender")
        self.assertEqual(body["subject"], "Hello")

        content_types = {content["type"] for content in body["content"]}
        self.assertEqual(content_types, {"text/plain", "text/html"})

        self.assertEqual(
            body["headers"]["List-Unsubscribe"], "<mailto:unsub@x.com>"
        )
        self.assertEqual(
            body["personalizations"][0]["custom_args"]["campaign"], "welcome"
        )

    def test_attachment_encoded_as_base64(self):
        import providers.sendgrid_provider as sendgrid_provider

        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "doc.pdf"
            pdf.write_bytes(b"%PDF-1.4 fake")

            with mock.patch.object(sendgrid_provider, "EMAIL_ADDRESS", "from@example.com"):
                body = sendgrid_provider.build_sendgrid_payload(
                    _payload(attachment_paths=[pdf], html_body="", extra_headers={})
                )

        attachment = body["attachments"][0]
        self.assertEqual(attachment["filename"], "doc.pdf")
        self.assertEqual(attachment["type"], "application/pdf")
        self.assertEqual(base64.b64decode(attachment["content"]), b"%PDF-1.4 fake")


class SESKwargsTests(unittest.TestCase):
    def test_send_kwargs_structure(self):
        import providers.ses_provider as ses_provider

        with mock.patch.object(ses_provider, "SES_FROM_ADDRESS", "verified@example.com"):
            kwargs = ses_provider.build_ses_send_kwargs(_payload())

        self.assertEqual(kwargs["FromEmailAddress"], "verified@example.com")
        self.assertEqual(kwargs["Destination"]["ToAddresses"], ["alice@example.com"])

        simple = kwargs["Content"]["Simple"]
        self.assertEqual(simple["Subject"]["Data"], "Hello")
        self.assertEqual(simple["Body"]["Text"]["Data"], "Hi")
        self.assertEqual(simple["Body"]["Html"]["Data"], "<p>Hi</p>")

        self.assertEqual(
            simple["Headers"],
            [{"Name": "List-Unsubscribe", "Value": "<mailto:unsub@x.com>"}],
        )

    def test_attachment_is_raw_bytes(self):
        import providers.ses_provider as ses_provider

        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "doc.pdf"
            pdf.write_bytes(b"%PDF-1.4 fake")

            with mock.patch.object(ses_provider, "SES_FROM_ADDRESS", "verified@example.com"):
                kwargs = ses_provider.build_ses_send_kwargs(
                    _payload(attachment_paths=[pdf])
                )

        attachment = kwargs["Content"]["Simple"]["Attachments"][0]
        self.assertEqual(attachment["Filename"], "doc.pdf")
        self.assertEqual(attachment["ContentType"], "application/pdf")
        self.assertEqual(attachment["RawContent"], b"%PDF-1.4 fake")


class GmailMessageTests(unittest.TestCase):
    def test_message_serializes_to_mime_with_sender_override(self):
        from providers.gmail_provider import build_gmail_message

        payload = EmailPayload(
            to_email="alice@example.com",
            subject="Hello",
            text_body="Hi",
            html_body="<p>Hi</p>",
            extra_headers={"List-Unsubscribe": "<mailto:unsub@x.com>"},
        )

        raw = build_gmail_message(payload, sender_email="thegmailaccount@gmail.com")

        message = message_from_bytes(base64.urlsafe_b64decode(raw))

        self.assertEqual(message["To"], "alice@example.com")
        self.assertEqual(message["Subject"], "Hello")
        self.assertEqual(message["List-Unsubscribe"], "<mailto:unsub@x.com>")
        self.assertIn("thegmailaccount@gmail.com", message["From"])


if __name__ == "__main__":
    unittest.main()
