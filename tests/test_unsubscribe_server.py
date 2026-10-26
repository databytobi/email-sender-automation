import tempfile
import unittest
from pathlib import Path
from unittest import mock

import unsubscribe_server
from unsubscribe import generate_token

SECRET = "server-test-secret"


class UnsubscribeHandlerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.suppression_path = Path(tmp.name) / "suppression.csv"

        mock.patch.object(unsubscribe_server, "UNSUBSCRIBE_SECRET", SECRET).start()
        mock.patch.object(
            unsubscribe_server, "SUPPRESSION_FILE", str(self.suppression_path)
        ).start()
        self.addCleanup(mock.patch.stopall)

    def test_valid_token_suppresses_address(self):
        email = "alice@example.com"
        token = generate_token(email, SECRET)

        handled = unsubscribe_server._handle_unsubscribe(email, token)

        self.assertTrue(handled)
        content = self.suppression_path.read_text(encoding="utf-8")
        self.assertIn(email, content)
        self.assertIn("Unsubscribed via link", content)

    def test_invalid_token_is_rejected(self):
        handled = unsubscribe_server._handle_unsubscribe(
            "alice@example.com", "wrong-token"
        )

        self.assertFalse(handled)
        self.assertFalse(self.suppression_path.exists())

    def test_missing_secret_refuses_everything(self):
        mock.patch.object(unsubscribe_server, "UNSUBSCRIBE_SECRET", "").start()

        email = "alice@example.com"
        token = generate_token(email, SECRET)

        self.assertFalse(unsubscribe_server._handle_unsubscribe(email, token))


if __name__ == "__main__":
    unittest.main()
