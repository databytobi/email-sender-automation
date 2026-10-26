import base64
import unittest

from bounces import parse_gmail_bounce


def _b64(text):
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


class ParseGmailBounceTests(unittest.TestCase):
    def test_x_failed_recipients_header(self):
        message = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "mailer-daemon@googlemail.com"},
                    {"name": "Subject", "value": "Delivery Status Notification"},
                    {
                        "name": "X-Failed-Recipients",
                        "value": "gone@example.com, also-gone@example.com",
                    },
                ],
                "mimeType": "multipart/report",
                "parts": [],
            }
        }

        self.assertEqual(
            parse_gmail_bounce(message),
            ["also-gone@example.com", "gone@example.com"],
        )

    def test_delivery_status_part_with_final_recipient(self):
        message = {
            "payload": {
                "headers": [{"name": "From", "value": "mailer-daemon@x.com"}],
                "mimeType": "multipart/report",
                "parts": [
                    {
                        "mimeType": "message/delivery-status",
                        "headers": [
                            {"name": "Final-Recipient", "value": "rfc822; bounced@example.com"},
                            {"name": "Action", "value": "failed"},
                            {"name": "Status", "value": "5.1.1"},
                        ],
                        "body": {"data": _b64("")},
                    }
                ],
            }
        }

        self.assertEqual(parse_gmail_bounce(message), ["bounced@example.com"])

    def test_final_recipient_in_encoded_body_text(self):
        dsn_text = (
            "Final-Recipient: rfc822; deep-bounce@example.com\r\n"
            "Action: failed\r\n"
        )
        message = {
            "payload": {
                "headers": [],
                "mimeType": "message/delivery-status",
                "body": {"data": _b64(dsn_text)},
                "parts": [],
            }
        }

        self.assertEqual(
            parse_gmail_bounce(message), ["deep-bounce@example.com"]
        )

    def test_no_bounce_information_yields_nothing(self):
        message = {
            "payload": {
                "headers": [{"name": "Subject", "value": "Hello"}],
                "mimeType": "text/plain",
                "body": {"data": _b64("just a normal email")},
                "parts": [],
            }
        }

        self.assertEqual(parse_gmail_bounce(message), [])


if __name__ == "__main__":
    unittest.main()
