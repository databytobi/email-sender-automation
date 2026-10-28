import tempfile
import unittest
from pathlib import Path

from loaders.recipient_loader import read_recipients, write_recipients


class ReadRecipientsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def _write(self, content):
        path = self.folder / "recipients.csv"
        path.write_text(content, encoding="utf-8")
        return path

    def test_reads_rows_and_strips_whitespace(self):
        path = self._write("Name,Email\n Alice , alice@example.com \n")

        recipients = read_recipients(path)

        self.assertEqual(
            recipients,
            [{"Name": "Alice", "Email": "alice@example.com"}],
        )

    def test_skips_duplicate_emails_case_insensitive(self):
        path = self._write("Name,Email\nAlice,a@example.com\nBob,A@Example.com\n")

        recipients = read_recipients(path)

        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0]["Name"], "Alice")

    def test_skips_blank_rows(self):
        path = self._write("Name,Email\nAlice,a@example.com\n,\n\nBob,b@example.com\n")

        recipients = read_recipients(path)

        self.assertEqual([r["Name"] for r in recipients], ["Alice", "Bob"])

    def test_missing_required_column_raises(self):
        path = self._write("Name,Phone\nAlice,123\n")

        with self.assertRaises(ValueError) as context:
            read_recipients(path)

        self.assertIn("Email", str(context.exception))

    def test_row_missing_email_raises_with_line_number(self):
        path = self._write("Name,Email\nAlice,a@example.com\nBob,\n")

        with self.assertRaises(ValueError) as context:
            read_recipients(path)

        self.assertIn("Row 3", str(context.exception))

    def test_row_missing_name_raises(self):
        path = self._write("Name,Email\n,a@example.com\n")

        with self.assertRaises(ValueError):
            read_recipients(path)

    def test_empty_file_raises(self):
        path = self._write("")

        with self.assertRaises(ValueError):
            read_recipients(path)

    def test_utf8_bom_from_excel_is_handled(self):
        path = self.folder / "recipients.csv"
        path.write_bytes("\ufeffName,Email\nAlice,a@example.com\n".encode("utf-8"))

        recipients = read_recipients(path)

        self.assertEqual(recipients[0]["Name"], "Alice")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_recipients(self.folder / "does-not-exist.csv")


class WriteRecipientsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.path = self.folder / "recipients.csv"

    def test_write_roundtrip_preserves_extra_columns(self):
        self.path.write_text(
            "Name,Email,Company\nAlice,a@x.com,ACME\n", encoding="utf-8"
        )

        recipients = read_recipients(self.path)
        recipients.append({"Name": "Bob", "Email": "b@x.com", "Company": "Globex"})

        write_recipients(self.path, recipients)

        reloaded = read_recipients(self.path)
        self.assertEqual(len(reloaded), 2)
        self.assertEqual(reloaded[0]["Company"], "ACME")
        self.assertEqual(reloaded[1]["Company"], "Globex")

    def test_write_from_scratch_creates_header(self):
        write_recipients(
            self.path, [{"Name": "Alice", "Email": "a@x.com"}]
        )

        content = self.path.read_text(encoding="utf-8")
        lines = content.strip().splitlines()

        self.assertEqual(lines[0], "Name,Email")
        self.assertEqual(len(read_recipients(self.path)), 1)

    def test_write_missing_column_filled_with_empty_value(self):
        self.path.write_text(
            "Name,Email,Company\nAlice,a@x.com,ACME\n", encoding="utf-8"
        )

        recipients = read_recipients(self.path)
        recipients.append({"Name": "Bob", "Email": "b@x.com"})

        write_recipients(self.path, recipients)

        reloaded = read_recipients(self.path)
        self.assertEqual(reloaded[1]["Company"], "")


if __name__ == "__main__":
    unittest.main()
