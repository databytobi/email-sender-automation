import tempfile
import unittest
from pathlib import Path

from suppression import (
    add_to_suppression,
    import_bounce_file,
    load_suppression,
    merge_bounces,
)


class SuppressionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.path = self.folder / "suppression.csv"

    def test_missing_file_loads_empty(self):
        self.assertEqual(load_suppression(self.path), {})

    def test_add_is_written_and_case_insensitive_on_load(self):
        added = add_to_suppression(self.path, "Bounced@Example.com", "bounced", "test")
        self.assertTrue(added)

        suppressed = load_suppression(self.path)
        self.assertIn("bounced@example.com", suppressed)

    def test_add_is_idempotent(self):
        self.assertTrue(add_to_suppression(self.path, "a@x.com", "bounced"))
        self.assertFalse(add_to_suppression(self.path, "A@X.com", "bounced again"))

        self.assertEqual(len(load_suppression(self.path)), 1)

    def test_merge_bounces_counts_only_new(self):
        added = merge_bounces(
            self.path,
            [
                {"email": "a@x.com", "reason": "hard bounce"},
                {"email": "A@X.com", "reason": "duplicate"},
                {"email": "", "reason": "ignored"},
            ],
            source="sync",
        )

        self.assertEqual(added, 1)

        row = load_suppression(self.path)["a@x.com"]
        self.assertEqual(row["Source"], "sync")

    def test_import_csv_with_email_column(self):
        csv_path = self.folder / "bounces.csv"
        csv_path.write_text("Email,Reason\nb@x.com,invalid\n", encoding="utf-8")

        added = import_bounce_file(csv_path, self.path)
        self.assertEqual(added, 1)
        self.assertIn("b@x.com", load_suppression(self.path))

    def test_import_plain_text_addresses(self):
        txt_path = self.folder / "bounces.txt"
        txt_path.write_text("one@x.com\ntwo@x.com\nnot-an-email\n\n", encoding="utf-8")

        added = import_bounce_file(txt_path, self.path)
        self.assertEqual(added, 2)

    def test_import_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            import_bounce_file(self.folder / "nope.csv", self.path)


if __name__ == "__main__":
    unittest.main()
