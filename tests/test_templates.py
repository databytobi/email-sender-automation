import unittest
from pathlib import Path

from main import personalize

TEMPLATES_FOLDER = Path(__file__).parent.parent / "templates"
CONTEXT = {"Name": "Alice", "Email": "alice@example.com"}


class TemplateTests(unittest.TestCase):
    def test_every_template_renders_with_the_available_columns(self):
        template_paths = sorted(TEMPLATES_FOLDER.glob("*.txt")) + sorted(
            TEMPLATES_FOLDER.glob("*.html")
        )

        self.assertTrue(template_paths, "no templates found")

        for path in template_paths:
            with self.subTest(template=path.name):
                rendered = personalize(
                    path.read_text(encoding="utf-8"), CONTEXT, path
                )
                self.assertIn("Alice", rendered)

    def test_placeholders_are_case_insensitive(self):
        self.assertEqual(personalize("Hi {name}!", CONTEXT, "x"), "Hi Alice!")
        self.assertEqual(personalize("Hi {Name}!", CONTEXT, "x"), "Hi Alice!")

    def test_unknown_placeholder_raises_clear_error(self):
        with self.assertRaises(ValueError) as context:
            personalize("Hi {nickname}!", CONTEXT, "template.txt")

        self.assertIn("Available columns", str(context.exception))


if __name__ == "__main__":
    unittest.main()
