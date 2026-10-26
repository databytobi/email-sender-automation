import unittest
from urllib.parse import parse_qs, urlparse

import unsubscribe
from unsubscribe import (
    append_footer,
    build_mailto_link,
    build_unsubscribe_headers,
    build_unsubscribe_link,
    generate_token,
    verify_token,
)

SECRET = "test-secret-123"


class TokenTests(unittest.TestCase):
    def test_token_is_stable_and_case_insensitive(self):
        self.assertEqual(
            generate_token("Alice@Example.com", SECRET),
            generate_token("alice@example.com", SECRET),
        )

    def test_token_verifies_roundtrip(self):
        token = generate_token("alice@example.com", SECRET)
        self.assertTrue(verify_token("alice@example.com", token, SECRET))

    def test_tampered_token_is_rejected(self):
        token = generate_token("alice@example.com", SECRET)
        self.assertFalse(verify_token("alice@example.com", "f" * 32, SECRET))
        self.assertFalse(verify_token("mallory@example.com", token, SECRET))

    def test_different_secret_different_token(self):
        self.assertNotEqual(
            generate_token("alice@example.com", SECRET),
            generate_token("alice@example.com", "other-secret"),
        )


class LinkTests(unittest.TestCase):
    def test_https_link_contains_verified_params(self):
        link = build_unsubscribe_link("alice@example.com", "https://u.example.com/", SECRET)

        parsed = urlparse(link)
        self.assertEqual(parsed.path, "/unsubscribe")
        query = parse_qs(parsed.query)

        self.assertEqual(query["email"], ["alice@example.com"])
        self.assertTrue(
            verify_token("alice@example.com", query["token"][0], SECRET)
        )

    def test_mailto_link_targets_configured_address(self):
        link = build_mailto_link("alice@example.com", "unsub@example.com", SECRET)

        self.assertTrue(link.startswith("mailto:unsub@example.com?subject="))


class HeaderTests(unittest.TestCase):
    def test_https_and_mailto_targets_combined(self):
        headers = build_unsubscribe_headers(
            https_link="https://u.example.com/unsubscribe?x=1",
            mailto_link="mailto:unsub@example.com",
        )

        self.assertIn("<https://u.example.com/unsubscribe?x=1>", headers["List-Unsubscribe"])
        self.assertIn("<mailto:unsub@example.com>", headers["List-Unsubscribe"])
        # One-click (RFC 8058) requires the HTTPS link.
        self.assertEqual(headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")

    def test_mailto_only_has_no_one_click_header(self):
        headers = build_unsubscribe_headers(mailto_link="mailto:unsub@example.com")

        self.assertIn("List-Unsubscribe", headers)
        self.assertNotIn("List-Unsubscribe-Post", headers)

    def test_no_targets_no_headers(self):
        self.assertEqual(build_unsubscribe_headers(), {})


class FooterTests(unittest.TestCase):
    def test_https_footer_added_to_both_bodies(self):
        text, html = append_footer(
            "Hello",
            "<p>Hello</p>",
            https_link="https://u.example.com/unsubscribe?x=1",
        )

        self.assertIn("https://u.example.com/unsubscribe?x=1", text)
        self.assertIn("https://u.example.com/unsubscribe?x=1", html)
        self.assertIn("Unsubscribe", text)
        self.assertIn("Unsubscribe", html)

    def test_mailto_footer_fallback(self):
        text, html = append_footer(
            "Hello", "<p>Hello</p>", mailto_link="mailto:unsub@example.com"
        )

        self.assertIn("mailto:unsub@example.com", text)
        self.assertIn("mailto:unsub@example.com", html)

    def test_text_footer_without_html_body(self):
        text, html = append_footer(
            "Hello", html_body="", https_link="https://u.example.com/x"
        )

        self.assertIn("Unsubscribe", text)
        self.assertEqual(html, "")


if __name__ == "__main__":
    unittest.main()
