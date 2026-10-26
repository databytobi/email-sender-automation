import tempfile
import unittest
from pathlib import Path
from unittest import mock

import state


class SentRegistryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.registry_path = self.folder / "sent_welcome.csv"

        patcher = mock.patch.object(state, "STATE_FOLDER", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_missing_registry_is_empty(self):
        self.assertEqual(state.load_sent_registry("welcome"), set())

    def test_record_and_load_roundtrip_is_case_insensitive(self):
        state.record_sent("welcome", "Alice@Example.com", backend="smtp")
        state.record_sent(
            "welcome", "bob@example.com", backend="sendgrid", message_id="sg-123"
        )

        loaded = state.load_sent_registry("welcome")

        self.assertEqual(loaded, {"alice@example.com", "bob@example.com"})

    def test_registry_file_has_header_and_fields(self):
        state.record_sent(
            "welcome", "bob@example.com", backend="ses", message_id="ses-1"
        )

        content = self.registry_path.read_text(encoding="utf-8")
        lines = content.strip().splitlines()

        self.assertEqual(lines[0], "Email,Date,Backend,MessageId")
        self.assertIn("bob@example.com", lines[1])
        self.assertIn("ses", lines[1])
        self.assertIn("ses-1", lines[1])

    def test_registry_is_per_campaign(self):
        state.record_sent("welcome", "alice@example.com")

        self.assertEqual(state.load_sent_registry("welcome"), {"alice@example.com"})
        self.assertEqual(state.load_sent_registry("newsletter"), set())

    def test_duplicate_rows_collapse_on_load(self):
        state.record_sent("welcome", "alice@example.com")
        state.record_sent("welcome", "alice@example.com")  # duplicate row

        self.assertEqual(state.load_sent_registry("welcome"), {"alice@example.com"})

    def test_clear_removes_existing_registry(self):
        state.record_sent("welcome", "alice@example.com")

        self.assertTrue(state.clear_sent_registry("welcome"))
        self.assertFalse(self.registry_path.exists())
        self.assertEqual(state.load_sent_registry("welcome"), set())

    def test_clear_without_registry_returns_false(self):
        self.assertFalse(state.clear_sent_registry("newsletter"))


if __name__ == "__main__":
    unittest.main()
