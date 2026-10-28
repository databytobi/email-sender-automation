import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import config
import state
from webapp import create_app

try:
    import flask  # noqa: F401
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

RECIPIENTS_CSV = "Name,Email\nAlice,alice@example.com\nBob,bob@example.com\nCarol,carol@example.com\n"


@unittest.skipUnless(FLASK_AVAILABLE, "flask is not installed")
class WebAppApiTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

        self.recipients = self.folder / "recipients.csv"
        self.recipients.write_text(RECIPIENTS_CSV, encoding="utf-8")

        patchers = [
            mock.patch.object(config, "RECIPIENTS_FILE", self.recipients),
            mock.patch.object(config, "SUPPRESSION_FILE", self.folder / "suppression.csv"),
            mock.patch.object(config, "REPORTS_FOLDER", self.folder / "reports"),
            mock.patch.object(state, "STATE_FOLDER", self.folder / "state"),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.client = create_app().test_client()

    # ---------- UI + static ----------

    def test_index_serves_the_spa(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Email Studio", response.data)

    def test_static_assets_served(self):
        for path in ("/css/app.css", "/js/app.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    # ---------- Overview & campaigns ----------

    def test_overview_counts(self):
        data = self.client.get("/api/overview").get_json()

        self.assertEqual(data["recipients"], 3)
        self.assertEqual(len(data["campaigns"]), 4)
        self.assertEqual(data["suppressed"], 0)
        self.assertIn("backend", data)
        self.assertIn("sender_email_masked", data)

    def test_campaigns_listed(self):
        data = self.client.get("/api/campaigns").get_json()

        self.assertEqual([c["type"] for c in data], ["certificate", "invoice", "newsletter", "welcome"])
        welcome = data[-1]
        self.assertEqual(welcome["subject"], "Welcome to Python Automation")

    def test_campaign_preview_renders_first_recipient(self):
        data = self.client.get("/api/campaigns/preview?type=welcome").get_json()

        self.assertIn("Alice", data["text_body"])
        self.assertIn("Alice", data["html_body"])
        self.assertEqual(data["recipient"]["Email"], "alice@example.com")

    def test_campaign_preview_rejects_unknown_type(self):
        response = self.client.get("/api/campaigns/preview?type=bogus")
        self.assertEqual(response.status_code, 400)

    # ---------- Campaign run ----------

    def test_live_run_requires_confirmation(self):
        response = self.client.post(
            "/api/campaigns/run",
            json={"email_type": "welcome", "dry_run": False, "confirmed": False},
        )

        self.assertEqual(response.status_code, 400)

    def test_dry_run_completes_and_saves_report(self):
        response = self.client.post(
            "/api/campaigns/run",
            json={"email_type": "welcome", "backend": "smtp", "dry_run": True},
        )
        self.assertEqual(response.status_code, 200)

        deadline = time.time() + 15
        while time.time() < deadline:
            status = self.client.get("/api/campaigns/status").get_json()

            if status["state"] != "running":
                break
            time.sleep(0.1)

        self.assertEqual(status["state"], "completed")
        self.assertEqual(status["progress"]["successful"], 3)
        self.assertEqual(status["progress"]["total"], 3)
        self.assertTrue(status["report_path"])

        # Report is a real CSV file with the dry-run rows
        report_file = Path(status["report_path"])
        self.assertTrue(report_file.is_file())
        self.assertIn("Dry-run", report_file.read_text(encoding="utf-8"))

        # Dry runs must never write send state
        self.assertFalse((self.folder / "state").exists())

    def test_second_run_while_running_is_rejected(self):
        # Not parallel-safe against other tests' timing, so use the
        # module runner directly: force it into 'running' state.
        from webapp import RUNNER

        RUNNER.state = "running"
        try:
            response = self.client.post(
                "/api/campaigns/run",
                json={"email_type": "welcome", "dry_run": True},
            )
            self.assertEqual(response.status_code, 409)
        finally:
            RUNNER.state = "idle"

    # ---------- Recipients CRUD ----------

    def test_recipient_add_duplicate_and_delete(self):
        total = self.client.get("/api/recipients").get_json()
        self.assertEqual(len(total), 3)

        # Add
        response = self.client.post(
            "/api/recipients", json={"name": "Dan", "email": "dan@example.com"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.client.get("/api/recipients").get_json()), 4)

        # Duplicate rejected
        duplicate = self.client.post(
            "/api/recipients", json={"name": "Dan", "email": "DAN@example.com"}
        )
        self.assertEqual(duplicate.status_code, 409)

        # Invalid email rejected
        invalid = self.client.post(
            "/api/recipients", json={"name": "Eve", "email": "not-an-email"}
        )
        self.assertEqual(invalid.status_code, 400)

        # Delete
        removed = self.client.delete("/api/recipients/dan%40example.com")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(len(self.client.get("/api/recipients").get_json()), 3)

        # File on disk reflects the change
        self.assertIn("Alice", self.recipients.read_text(encoding="utf-8"))
        self.assertNotIn("Dan", self.recipients.read_text(encoding="utf-8"))

    # ---------- Suppression CRUD ----------

    def test_suppression_add_and_remove(self):
        self.client.post(
            "/api/suppression", json={"email": "bounced@example.com", "reason": "hard bounce"}
        )

        rows = self.client.get("/api/suppression").get_json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Email"], "bounced@example.com")
        self.assertIn("hard bounce", rows[0]["Reason"])

        self.client.delete("/api/suppression/bounced%40example.com")
        self.assertEqual(self.client.get("/api/suppression").get_json(), [])

    # ---------- Reports ----------

    def test_reports_list_and_detail(self):
        self.client.post(
            "/api/campaigns/run",
            json={"email_type": "welcome", "dry_run": True},
        )

        deadline = time.time() + 15
        while time.time() < deadline:
            status = self.client.get("/api/campaigns/status").get_json()
            if status["state"] != "running":
                break
            time.sleep(0.1)

        reports = self.client.get("/api/reports").get_json()
        self.assertEqual(len(reports), 1)

        detail = self.client.get(f"/api/reports/{reports[0]['file']}").get_json()
        self.assertEqual(len(detail["rows"]), 3)

    def test_report_path_traversal_is_blocked(self):
        response = self.client.get("/api/reports/..%2F..%2Fconfig.py")
        self.assertEqual(response.status_code, 404)

    # ---------- Registries ----------

    def test_registries_list_and_clear(self):
        registries = self.client.get("/api/registries").get_json()

        self.assertEqual(len(registries), 4)
        self.assertTrue(all(r["count"] == 0 for r in registries))

        cleared = self.client.delete("/api/registries/welcome").get_json()
        self.assertFalse(cleared["ok"])  # nothing existed

    def test_registry_clear_rejects_unknown_campaign(self):
        response = self.client.delete("/api/registries/bogus")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
