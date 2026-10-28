"""Web control panel for the Email Sender Automation project.

A Flask app that serves a single-page UI (web/) and a JSON API
reusing the exact same modules as the CLI — campaigns, recipients,
suppression, sent registries, and delivery reports.

Run it locally:
    pip install flask
    python webapp.py
    open http://127.0.0.1:5000

Security notes:
- Binds to 127.0.0.1 by default — it is a local tool, do not expose
  it to the internet without adding authentication.
- API responses never include secrets: addresses are masked, and only
  booleans are exposed for credential-type settings.
- Live sends require the same explicit confirmation as the CLI: the
  UI must POST {"confirmed": true}.
- Only one campaign runs at a time; dry runs never write send state.
"""

import threading
import time
from pathlib import Path

import config
from config import EMAIL_CONFIG, VALID_BACKENDS, unsubscribe_settings
from loaders.recipient_loader import read_recipients, write_recipients
from loaders.template_loader import read_template
from logger import logger, mask_email
from main import render_bodies
from providers import create_delivery_provider
from providers.base import AuthDeliveryError, EmailPayload, RetryableDeliveryError
from reports.report_generator import save_report
from state import clear_sent_registry, load_sent_registry, sent_registry_path
from suppression import load_suppression

WEB_FOLDER = Path(__file__).parent / "web"

SAMPLE_RECIPIENT = {"Name": "Sample Recipient", "Email": "sample@example.com"}


class CampaignRunner:
    """Runs one campaign in a background thread with live progress.

    Mirrors the CLI semantics: suppression check first, optional
    --resume skip, HTML-escaped rendering, reconnect-and-retry once,
    abort on auth errors, record_sent after every live success, and a
    timestamped report even for aborted runs.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self.state = "idle"  # idle | running | completed | aborted | failed
        self.email_type = None
        self.backend = None
        self.dry_run = True
        self.resume = False
        self.progress = {
            "total": 0,
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "suppressed": 0,
            "resumed": 0,
            "current": "",
        }
        self.report = []
        self.error = None
        self.report_path = None
        self.started_at = None
        self.finished_at = None
        self._cancel = False

    @property
    def busy(self):
        return self.state == "running"

    def start(self, email_type, backend, dry_run, resume):
        with self._lock:
            if self.busy:
                raise RuntimeError("A campaign is already running")

            self.reset()
            self.email_type = email_type
            self.backend = backend
            self.dry_run = dry_run
            self.resume = resume
            self.state = "running"
            self.started_at = time.time()

            threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        if self.busy:
            self._cancel = True
            return True
        return False

    def snapshot(self):
        return {
            "state": self.state,
            "email_type": self.email_type,
            "backend": self.backend,
            "dry_run": self.dry_run,
            "resume": self.resume,
            "progress": dict(self.progress),
            "report_rows": len(self.report),
            "error": self.error,
            "report_path": str(self.report_path) if self.report_path else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def _finish(self, state, error=None):
        self.state = state
        self.error = error
        self.finished_at = time.time()
        self.progress["current"] = ""

    def _save_report(self):
        if not self.report:
            return

        self.report_path = config.REPORTS_FOLDER / (
            f"email_report_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        )
        save_report(self.report, self.report_path)

    def _run(self):
        try:
            self._run_campaign()
        except AuthDeliveryError as error:
            logger.error(str(error))
            self._finish("failed", str(error))
        except Exception as error:
            logger.exception("Campaign runner crashed")
            self._finish("failed", str(error))

    def _run_campaign(self):
        from config import validate_configuration

        try:
            validate_configuration(
                email_type=self.email_type,
                check_credentials=not self.dry_run,
                backend=self.backend,
            )
        except ValueError as error:
            self._finish("failed", str(error))
            return

        campaign = EMAIL_CONFIG[self.email_type]

        try:
            recipients = read_recipients(config.RECIPIENTS_FILE)
        except (FileNotFoundError, ValueError) as error:
            self._finish("failed", str(error))
            return

        suppression = load_suppression(config.SUPPRESSION_FILE)
        already_sent = load_sent_registry(self.email_type) if self.resume else set()
        unsubscribe = unsubscribe_settings()

        text_template = read_template(campaign["text_template"])
        html_template = read_template(campaign["html_template"])

        self.progress["total"] = len(recipients)

        provider = None

        try:
            if not self.dry_run:
                provider = create_delivery_provider(self.backend)
                provider.connect()

            for recipient in recipients:
                if self._cancel:
                    self._finish("aborted")
                    break

                self.progress["current"] = recipient["Name"]
                email_key = recipient["Email"].lower()

                if email_key in suppression:
                    self.progress["suppressed"] += 1
                    self.progress["processed"] += 1
                    self.report.append(
                        {
                            "Name": recipient["Name"],
                            "Email": recipient["Email"],
                            "Status": "Suppressed",
                            "Error": "On suppression list",
                        }
                    )
                    continue

                if self.resume and email_key in already_sent:
                    self.progress["resumed"] += 1
                    self.progress["processed"] += 1
                    self.report.append(
                        {
                            "Name": recipient["Name"],
                            "Email": recipient["Email"],
                            "Status": "Already sent",
                            "Error": "Skipped by resume",
                        }
                    )
                    continue

                try:
                    text_body, html_body, headers = render_bodies(
                        campaign,
                        recipient,
                        text_template,
                        html_template,
                        unsubscribe,
                    )
                except ValueError as error:
                    self.progress["processed"] += 1
                    self.progress["failed"] += 1
                    self.report.append(
                        {
                            "Name": recipient["Name"],
                            "Email": recipient["Email"],
                            "Status": "Failed",
                            "Error": str(error),
                        }
                    )
                    continue

                payload = EmailPayload(
                    to_email=recipient["Email"],
                    subject=campaign["subject"],
                    text_body=text_body,
                    html_body=html_body,
                    attachment_paths=campaign["attachments"],
                    extra_headers=headers,
                    custom_args={"campaign": self.email_type},
                )

                if self.dry_run:
                    result = {"success": True, "error": None, "message_id": None}
                else:
                    attempts = 2
                    while True:
                        try:
                            result = provider.send(payload)
                            break
                        except RetryableDeliveryError as error:
                            if attempts > 1:
                                attempts -= 1
                                logger.warning(f"Reconnecting: {error}")
                                provider.reconnect()
                            else:
                                result = {
                                    "success": False,
                                    "error": f"Connection lost after retry: {error}",
                                    "message_id": None,
                                }
                                break

                self.progress["processed"] += 1

                if result["success"]:
                    self.progress["successful"] += 1
                    if not self.dry_run and email_key not in already_sent:
                        record_sent(
                            self.email_type,
                            recipient["Email"],
                            backend=self.backend,
                            message_id=result.get("message_id") or "",
                        )
                        already_sent.add(email_key)
                else:
                    self.progress["failed"] += 1

                status = (
                    "Dry-run"
                    if self.dry_run
                    else ("Sent" if result["success"] else "Failed")
                )

                self.report.append(
                    {
                        "Name": recipient["Name"],
                        "Email": recipient["Email"],
                        "Status": status,
                        "Error": result["error"] or "-",
                    }
                )
            else:
                self._finish("completed")
        finally:
            if provider is not None:
                try:
                    provider.close()
                except Exception:
                    logger.warning("Could not close the delivery session cleanly.")

            self._save_report()
            logger.info(
                f"Web campaign finished: state={self.state}, "
                f"successful={self.progress['successful']}, "
                f"failed={self.progress['failed']}"
            )


RUNNER = CampaignRunner()


def _campaign_info(email_type):
    campaign = EMAIL_CONFIG[email_type]
    attachments = []

    for path in campaign.get("attachments", []):
        attachments.append(
            {"name": Path(path).name, "exists": Path(path).is_file()}
        )

    return {
        "type": email_type,
        "subject": campaign["subject"],
        "attachments": attachments,
    }


def _overview_payload():
    runs = []

    reports = sorted(
        config.REPORTS_FOLDER.glob("email_report_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for path in reports[:6]:
        runs.append(
            {
                "file": path.name,
                "size": path.stat().st_size,
                "modified": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)
                ),
            }
        )

    unsubscribe = unsubscribe_settings()

    return {
        "recipients": len(read_recipients(config.RECIPIENTS_FILE)),
        "campaigns": sorted(EMAIL_CONFIG.keys()),
        "suppressed": len(load_suppression(config.SUPPRESSION_FILE)),
        "sent_total": sum(
            len(load_sent_registry(email_type)) for email_type in EMAIL_CONFIG
        ),
        "backend": config.DELIVERY_BACKEND,
        "unsubscribe_enabled": unsubscribe is not None,
        "unsubscribe_mode": (
            "https + mailto"
            if unsubscribe and unsubscribe["base_url"] and unsubscribe["mailto"]
            else "https"
            if unsubscribe and unsubscribe["base_url"]
            else "mailto"
            if unsubscribe
            else None
        ),
        "sender_name": config.SENDER_NAME,
        "sender_email_masked": (
            mask_email(config.EMAIL_ADDRESS) if config.EMAIL_ADDRESS else None
        ),
        "smtp_server": config.SMTP_SERVER,
        "recent_runs": runs,
    }


def create_app():
    """Build the Flask app. Flask is imported lazily (optional dep)."""
    try:
        from flask import Flask, jsonify, request, send_file
    except ImportError:
        raise SystemExit(
            "The web UI requires Flask. Install it with: pip install flask"
        )

    app = Flask(__name__, static_folder=WEB_FOLDER, static_url_path="")
    app.config["JSON_SORT_KEYS"] = False

    def api_error(message, status=400):
        return jsonify({"error": message}), status

    # ---------- UI ----------

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    # ---------- Overview / campaigns ----------

    @app.get("/api/overview")
    def overview():
        try:
            return jsonify(_overview_payload())
        except FileNotFoundError as error:
            return api_error(str(error), 500)

    @app.get("/api/campaigns")
    def campaigns():
        return jsonify([_campaign_info(t) for t in sorted(EMAIL_CONFIG)])

    @app.get("/api/campaigns/preview")
    def campaign_preview():
        email_type = request.args.get("type")
        if email_type not in EMAIL_CONFIG:
            return api_error(f"Unknown campaign type: {email_type!r}")

        campaign = EMAIL_CONFIG[email_type]

        try:
            recipients = read_recipients(config.RECIPIENTS_FILE)
        except (FileNotFoundError, ValueError):
            recipients = []

        index = request.args.get("recipient_index", type=int)
        recipient = (
            recipients[index]
            if recipients and index is not None and 0 <= index < len(recipients)
            else (recipients[0] if recipients else SAMPLE_RECIPIENT)
        )

        try:
            text_body, html_body, _headers = render_bodies(
                campaign,
                recipient,
                read_template(campaign["text_template"]),
                read_template(campaign["html_template"]),
                unsubscribe_settings(),
            )
        except ValueError as error:
            return api_error(str(error))

        return jsonify(
            {
                "email_type": email_type,
                "subject": campaign["subject"],
                "recipient": recipient,
                "text_body": text_body,
                "html_body": html_body,
            }
        )

    @app.post("/api/campaigns/run")
    def campaign_run():
        data = request.get_json(silent=True) or {}

        email_type = data.get("email_type")
        backend = data.get("backend", config.DELIVERY_BACKEND)
        dry_run = bool(data.get("dry_run", False))
        resume = bool(data.get("resume", False))

        if email_type not in EMAIL_CONFIG:
            return api_error(f"Unknown campaign type: {email_type!r}")
        if backend not in VALID_BACKENDS:
            return api_error(f"Unknown backend: {backend!r}")
        if not dry_run and not data.get("confirmed"):
            return api_error(
                "Live sends require explicit confirmation "
                "(the same rule as the CLI's YES prompt).", 400
            )
        if RUNNER.busy:
            return api_error("A campaign is already running.", 409)

        try:
            RUNNER.start(email_type, backend, dry_run, resume)
        except RuntimeError as error:
            return api_error(str(error), 409)

        return jsonify({"ok": True, "state": RUNNER.snapshot()})

    @app.get("/api/campaigns/status")
    def campaign_status():
        return jsonify(RUNNER.snapshot())

    @app.post("/api/campaigns/cancel")
    def campaign_cancel():
        return jsonify({"ok": RUNNER.cancel()})

    # ---------- Recipients ----------

    @app.get("/api/recipients")
    def recipients_list():
        return jsonify(read_recipients(config.RECIPIENTS_FILE))

    @app.post("/api/recipients")
    def recipients_add():
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()

        if not name or not email:
            return api_error("Both name and email are required.")
        if "@" not in email:
            return api_error(f"'{email}' is not a valid email address.")

        recipients = read_recipients(config.RECIPIENTS_FILE)

        if any(r["Email"].lower() == email.lower() for r in recipients):
            return api_error(f"{email} is already on the list.", 409)

        recipients.append({"Name": name, "Email": email})
        write_recipients(config.RECIPIENTS_FILE, recipients)

        return jsonify({"ok": True, "total": len(recipients)})

    @app.delete("/api/recipients/<email>")
    def recipients_delete(email):
        recipients = read_recipients(config.RECIPIENTS_FILE)
        remaining = [r for r in recipients if r["Email"].lower() != email.lower()]

        if len(remaining) == len(recipients):
            return api_error(f"{email} was not found.", 404)

        write_recipients(config.RECIPIENTS_FILE, remaining)
        return jsonify({"ok": True, "total": len(remaining)})

    # ---------- Suppression ----------

    @app.get("/api/suppression")
    def suppression_list():
        rows = load_suppression(config.SUPPRESSION_FILE)
        return jsonify(
            [
                {
                    "Email": data.get("Email", email),
                    "Reason": data.get("Reason", ""),
                    "Source": data.get("Source", ""),
                    "Date": data.get("Date", ""),
                }
                for email, data in sorted(rows.items())
            ]
        )

    @app.post("/api/suppression")
    def suppression_add():
        from suppression import add_to_suppression

        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip()
        reason = (data.get("reason") or "manual (web)").strip()

        if not email or "@" not in email:
            return api_error("A valid email address is required.")

        added = add_to_suppression(
            config.SUPPRESSION_FILE, email, reason, source="web-ui"
        )

        return jsonify({"ok": True, "added": added})

    @app.delete("/api/suppression/<email>")
    def suppression_delete(email):
        path = Path(config.SUPPRESSION_FILE)

        if not path.is_file():
            return api_error("No suppression list exists.", 404)

        import csv as _csv

        with path.open("r", newline="", encoding="utf-8-sig") as file:
            reader = _csv.DictReader(file)
            fieldnames = reader.fieldnames or []
            rows = [row for row in reader if (row.get("Email") or "").lower() != email.lower()]

        with path.open("w", newline="", encoding="utf-8") as file:
            writer = _csv.DictWriter(file, fieldnames=fieldnames or ["Email", "Reason", "Source", "Date"])
            writer.writeheader()
            writer.writerows(rows)

        return jsonify({"ok": True})

    # ---------- Reports ----------

    @app.get("/api/reports")
    def reports_list():
        reports = sorted(
            config.REPORTS_FOLDER.glob("email_report_*.csv"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return jsonify(
            [
                {
                    "file": path.name,
                    "size": path.stat().st_size,
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)
                    ),
                }
                for path in reports
            ]
        )

    @app.get("/api/reports/<path:name>")
    def report_detail(name):
        safe_name = Path(name).name
        path = config.REPORTS_FOLDER / safe_name

        if not path.is_file() or path.parent != config.REPORTS_FOLDER:
            return api_error("Report not found.", 404)

        import csv as _csv

        with path.open("r", newline="", encoding="utf-8-sig") as file:
            rows = list(_csv.DictReader(file))

        return jsonify({"file": safe_name, "rows": rows})

    @app.get("/api/reports/<path:name>/download")
    def report_download(name):
        safe_name = Path(name).name
        path = config.REPORTS_FOLDER / safe_name

        if not path.is_file() or path.parent != config.REPORTS_FOLDER:
            return api_error("Report not found.", 404)

        return send_file(path, as_attachment=True, download_name=safe_name)

    # ---------- Sent registries (auto-resume) ----------

    @app.get("/api/registries")
    def registries_list():
        result = []

        for email_type in sorted(EMAIL_CONFIG):
            emails = sorted(load_sent_registry(email_type))
            result.append(
                {
                    "campaign": email_type,
                    "count": len(emails),
                    "emails": emails,
                    "file": str(sent_registry_path(email_type)),
                }
            )

        return jsonify(result)

    @app.delete("/api/registries/<campaign>")
    def registry_clear(campaign):
        if campaign not in EMAIL_CONFIG:
            return api_error(f"Unknown campaign type: {campaign!r}")

        removed = clear_sent_registry(campaign)
        return jsonify({"ok": removed})

    return app


if __name__ == "__main__":
    import os

    app = create_app()

    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
