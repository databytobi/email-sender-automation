# 📧 Email Sender Automation

Python 3.10+ · MIT License · Status: Completed · PRs Welcome

A professional Python email automation system built for learning, teaching, and real-world automation.

This project demonstrates how to build a production-style email sender that supports personalized emails, HTML templates, attachments, logging, reporting, error handling, and Windows Task Scheduler integration.

---

## ✨ Features

- Send personalized emails from a CSV file
- **Pluggable delivery backends**: SMTP (default), **Gmail API**, **SendGrid**, **Amazon SES**
- **Unsubscribe support**: HMAC-signed links, `List-Unsubscribe` + one-click (RFC 8058) headers, optional web app
- **Bounce processing**: pull bounces from Gmail/SendGrid/SES or import from a file into a permanent suppression list
- Suppression list checked before every campaign — bounces, complaints, and unsubscribes are never emailed again
- **Auto-resume** (`--resume`): re-run a crashed or interrupted campaign and skip everyone already sent
- Plain-text and HTML email support
- Multiple email templates and attachments
- **Dry-run mode** — preview a campaign without sending anything
- **Confirmation prompt** — a live campaign never sends without an explicit go-ahead
- One reusable delivery session per campaign (fast, avoids provider rate-limit flags)
- Automatic reconnect-and-retry when the connection drops mid-campaign
- Secure SMTP authentication using environment variables (TLS with certificate validation)
- Recipient CSV validation: required columns, blank rows, and duplicate emails
- HTML-escaped personalization (CSV values cannot inject markup into emails)
- Rotating log files with privacy-masked email addresses
- Console progress bar with `tqdm`
- Timestamped CSV delivery reports (previous runs are never overwritten)
- Exit codes for Task Scheduler / CI integration
- Unit test suite included
- Modular project structure

---

## 📁 Project Structure

```
Email Sender Automation/
│
├── attachments/          # campaign PDFs (supply your own; not committed)
├── loaders/
│   ├── recipient_loader.py
│   └── template_loader.py
├── logs/                 # rotating log files (created at runtime)
├── providers/            # pluggable delivery backends
│   ├── base.py           # EmailPayload + DeliveryProvider interface
│   ├── smtp_provider.py
│   ├── gmail_provider.py
│   ├── sendgrid_provider.py
│   └── ses_provider.py
├── reports/
│   ├── report_generator.py
│   └── email_report_YYYYMMDD_HHMMSS.csv   # generated per run
├── scripts/
│   └── run_email_automation.bat
├── state/                # sent registries for --resume (created at runtime)
├── templates/            # .txt + .html pairs, personalize with {Name} etc.
├── tests/                # unit tests (python -m unittest discover)
├── bounces.py            # DSN parsing for bounce processing
├── suppression.py        # suppression list management
├── state.py              # sent registries for auto-resume
├── unsubscribe.py        # tokens, footers, List-Unsubscribe headers
├── unsubscribe_server.py # optional web app (RFC 8058 one-click)
├── config.py
├── logger.py
├── main.py
├── sender.py
├── recipients.csv        # your recipient list (never commit real data)
├── recipients_example.csv
├── requirements.txt      # core dependencies
├── requirements-esp.txt  # optional extras for ESP backends
├── .env                  # your secrets (never commit)
├── .env.example
├── .gitignore
└── README.md
```

---

## 🚀 Installation

Clone the repository

```bash
git clone https://github.com/yourusername/email-sender-automation.git
cd email-sender-automation
```

Create and activate a virtual environment

```bash
python -m venv my_venv

# Windows
my_venv\Scripts\activate

# macOS/Linux
source my_venv/bin/activate
```

Install dependencies (versions are pinned for reproducible setups)

```bash
pip install -r requirements.txt
```

Add the campaign attachments you need to `attachments/` (e.g. `invoice.pdf`,
`certificate.pdf`, `newsletter.pdf`). Personal documents are **not** committed
to the repository.

---

## 🔐 Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
EMAIL_ADDRESS=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_NAME=Your Name
EMAIL_TYPE=welcome
RECIPIENTS_FILE=recipients.csv
```

> **Note:** If you're using Gmail, create an [App Password](https://support.google.com/accounts/answer/185833)
> instead of using your normal account password.

> **Privacy:** `recipients.csv`, `suppression.csv`, `client_secret.json`,
> `gmail_token.json`, and `.env` are gitignored on purpose. Real recipient
> data and credentials must never be committed.

---

## 🚚 Delivery Backends (choose where mail goes)

Set `DELIVERY_BACKEND` in `.env` (or use `--backend` on the command line).
All backends share the same campaign loop, retry logic, and reports.

### `smtp` — classic SMTP (default, zero extra dependencies)

Best for: small personal lists, learning. Consumer Gmail caps ~500
recipients/day and flags bulk sending — that's what the ESP backends below
are for. Uses `SMTP_SERVER`/`SMTP_PORT`/`EMAIL_ADDRESS`/`EMAIL_PASSWORD`.

### `gmail` — Gmail API with OAuth2 (no app password)

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

1. In [Google Cloud Console](https://console.cloud.google.com/) enable the
   **Gmail API**, then create an **OAuth client ID** (type *Desktop app*) and
   download `client_secret.json` into the project.
2. Set `DELIVERY_BACKEND=gmail` and run a live campaign once — a browser
   opens for consent; the token is cached in `gmail_token.json` for
   scheduled runs.
3. Bonus: `--sync-bounces` scans your INBOX for `mailer-daemon` bounce
   notifications and suppresses those addresses automatically.

### `sendgrid` — SendGrid v3 API (bulk-safe)

```bash
pip install requests
```

1. Create an API key at [app.sendgrid.com/settings/api_keys](https://app.sendgrid.com/settings/api_keys).
2. Verify your `EMAIL_ADDRESS` as a sender in SendGrid.
3. Set `DELIVERY_BACKEND=sendgrid` and `SENDGRID_API_KEY`.
4. `--sync-bounces` pulls SendGrid's bounce list (also configure a
   [webhook](https://app.sendgrid.com/settings/mail_settings) for
   real-time events if you host the app).

### `ses` — Amazon SES v2 (bulk-safe)

```bash
pip install boto3
```

1. Verify a sending identity and set `SES_FROM_ADDRESS` + `AWS_REGION`
   (credentials come from the standard boto3 chain).
2. Note: in SES **sandbox mode** every recipient must also be verified —
   request production access first.
3. `--sync-bounces` reads the SES account suppression list (SES adds
   hard bounces/complaints automatically).

---

## 🔗 Unsubscribe & Suppression (CAN-SPAM / GDPR)

Every campaign email gets an unsubscribe footer plus
`List-Unsubscribe` / `List-Unsubscribe-Post` headers — Gmail surfaces
these as a native Unsubscribe button. Configure in `.env`:

```env
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
UNSUBSCRIBE_SECRET=...

# Option A: hosted one-click unsubscribe (RFC 8058)
UNSUBSCRIBE_BASE_URL=https://your-unsubscribe-app.onrender.com

# Option B: mailto fallback (works with zero hosting)
UNSUBSCRIBE_MAILTO=unsubscribe@yourdomain.com
```

- Unsubscribe tokens are **stateless HMAC signatures** — no database; the
  same secret verifies clicks forever.
- Every click (or one-click POST) lands in `suppression.csv`, and
  suppressed addresses are skipped with a `Suppressed` report row before
  every send. You can also manage the file manually:
  `Email, Reason, Source, Date`.
- Running a live campaign with **no unsubscribe configuration** prints a
  prominent compliance warning. Use `--no-unsubscribe` only for
  transactional/one-to-one mail.

### Hosting the one-click endpoint

Deploy `unsubscribe_server.py` (Flask, ~60 lines) anywhere that runs
Python — Render/Railway/a small VPS:

```bash
pip install flask
python unsubscribe_server.py          # test locally at :5000
```

Set `UNSUBSCRIBE_SECRET` and `SUPPRESSION_FILE` in the server's
environment. If the server runs on a different machine than the
campaign, merge its `suppression.csv` back (e.g. copy it and run
`python main.py --import-bounces copy.csv`).

---

## 📨 Bounce Processing

Bounced addresses go into the suppression list so they are never mailed
again. Three ways to get them in:

```bash
# Pull from the backend (gmail: INBOX DSN scan; sendgrid: bounce list;
# ses: account suppression list; smtp: prints guidance instead)
python main.py --sync-bounces

# Import from a CSV (Email column) or one-address-per-line text file
python main.py --import-bounces bounces.csv
python main.py --import-bounces bounces.txt

# Unsubscribe clicks are added automatically by the web app
```

Schedule `--sync-bounces` daily alongside your campaign for hands-off
hygiene. The Gmail parser understands both Google's `X-Failed-Recipients`
header and standard RFC 3464 `message/delivery-status` parts.

---

## 🔁 Auto-Resume

Every live send is recorded the moment it succeeds in a per-campaign
registry (`state/sent_<type>.csv`), so a crash right after a send still
leaves it resumable. If a run dies mid-campaign:

```bash
python main.py --resume
```

Registered addresses are skipped (report status `Already sent`) and the
campaign continues where it stopped. Combine with `--dry-run` to preview
exactly who would be skipped before going live.

Before an **intentional** re-send of the same campaign type, clear the
registry first — otherwise `--resume` would skip everyone:

```bash
python main.py --reset-sent
```

Notes: registries are keyed per campaign type (not per backend), so
switching backends mid-campaign still resumes correctly; dry runs never
write to the registry; the `state/` folder is gitignored.

---

## ▶️ Running the Project

Always start with a dry run to preview what would be sent:

```bash
python main.py --dry-run
```

This validates your configuration, renders every email (with your real
templates and data), and writes a `reports/email_report_<timestamp>.csv`
marked `Dry-run` — without connecting to any mail server (no credentials
needed).

When you are happy with the result, do a live run:

```bash
python main.py
```

You will see a summary and be asked to confirm before a single email goes out:

```
⚠  LIVE CAMPAIGN READY — emails will be sent
============================================================
Campaign type : welcome
Backend       : sendgrid
Subject       : Welcome to Python Automation
Recipients    : 8
============================================================
Proceed? Type YES to continue:
```

### Command-line options

| Option | Description |
| --- | --- |
| `--dry-run` | Render and report without sending (no credentials needed) |
| `--yes`, `-y` | Skip the confirmation prompt (required for scheduled tasks) |
| `--type {welcome,invoice,certificate,newsletter}` | Campaign type (overrides `EMAIL_TYPE`) |
| `--recipients PATH` | Recipients CSV file (overrides `RECIPIENTS_FILE`) |
| `--backend {smtp,gmail,sendgrid,ses}` | Delivery backend (overrides `DELIVERY_BACKEND`) |
| `--no-unsubscribe` | Skip the unsubscribe footer/headers (transactional mail only) |
| `--sync-bounces` | Pull bounces from the backend into the suppression list, then exit |
| `--import-bounces FILE` | Import bounced addresses from a CSV/text file into the suppression list, then exit |
| `--resume` | Skip recipients already successfully sent in a previous run of this campaign type (use after a crash/interruption) |
| `--reset-sent` | Delete the sent registry for the selected campaign type (before an intentional re-send), then exit |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | All emails sent successfully (or dry run rendered) |
| 1 | Configuration/recipient error, user declined, or some sends failed |
| 2 | SMTP connection or authentication problem — campaign aborted |
| 130 | Aborted by user (Ctrl+C) — partial report is saved |

### Recipients CSV format

The file must have `Name` and `Email` columns. Any extra columns become extra
template placeholders:

```csv
Name,Email,Company
John Doe,john@example.com,ACME
```

Templates can use `{Name}`, `{Email}`, `{Company}`, and so on. Whitespace is
trimmed, blank rows are skipped, and duplicate email addresses are skipped
with a warning.

---

## 📊 Output

Every run produces:

- A live `tqdm` progress bar
- A console summary (mode, counts, success rate, duration)
- A **timestamped** CSV delivery report in `reports/` (past reports are kept)
- Rotating log files in `logs/` (emails are privacy-masked in logs)

---

## 🖥 Web UI — Email Studio

A modern, single-page web control panel built with plain HTML/CSS/JS
(no build step, works fully offline) served by Flask. It wraps the exact
same modules as the CLI — campaigns, recipients, suppression, sent
registries, and delivery reports — so nothing diverges between the UI and
the command line.

### Getting started

```bash
pip install flask          # also listed in requirements-esp.txt
python webapp.py
```

Then open **http://127.0.0.1:5000** (override host/port with the `HOST`
and `PORT` environment variables).

### What you can do from the UI

| Page | Capabilities |
| --- | --- |
| Dashboard | recipient / suppressed / registry counts, delivery setup, recent runs |
| Campaigns | preview each campaign's rendered email, dry-run, or launch a send |
| Recipients | view, add, remove recipients from `recipients.csv` |
| Suppression | add/remove suppressed addresses (bounces, complaints, unsubscribes) |
| Reports | browse timestamped reports, open row-by-row status, download CSV |
| Auto-Resume | view per-campaign sent registries, clear them before a re-send |
| Settings | non-secret config summary (backend, sender, unsubscribe mode) |

### Safety by design

- **Binds to `127.0.0.1`** — local machine only; never expose it to the internet without adding authentication.
- **Live sends require explicit confirmation** — the same rule as typing `YES` in the CLI.
- **No secrets ever reach the browser** — addresses are masked; credentials are never returned.
- **One campaign at a time**; runs can be aborted and their partial report is still saved.
- Dry runs never write to the sent registry and never send mail.

> The web UI complements `unsubscribe_server.py` (the optional hosted
> one-click unsubscribe endpoint) — one runs your local control panel,
> the other hosts RFC 8058 unsubscribe clicks for your live campaigns.

---

## 📅 Scheduling (Windows Task Scheduler)

Use the included batch script. Non-interactive runs must pass `--yes`:

```
scripts\run_email_automation.bat --yes
```

The script locates the project relative to itself, uses the project venv when
available (falling back to system Python), passes arguments through, and
propagates the exit code so Task Scheduler can detect failures.

A healthy schedule for real campaigns: run `--sync-bounces` daily so bounced
addresses are suppressed before the next send.

> **Bulk sending limits & compliance:** consumer Gmail SMTP caps at ~500
> recipients/day and its ToS discourages bulk mail — use the `sendgrid` or
> `ses` backend for real lists, keep the unsubscribe footer enabled, and
> process bounces.

---

## 🧪 Running the Tests

```bash
python -m unittest discover -v
```

The 94-test suite covers the recipient loader (validation, duplicates, BOM
handling), the sender (message construction, MIME types, header injection,
reconnect semantics), configuration and backend validation, the unsubscribe
token/footer/header machinery, suppression, bounce parsing, the sent
registries for auto-resume, and every provider's payload builder — all
without network access or optional dependencies installed.

---

## 🛠 Technologies Used

- Python 3.10+
- `smtplib` + `email.message.EmailMessage`
- `ssl` (TLS with certificate validation)
- `python-dotenv`
- `tqdm`
- `logging` (rotating handlers)
- `pathlib`, `csv`, `argparse`, `mimetypes`, `hmac` (unsubscribe tokens)
- Optional extras: `requests` (SendGrid), `google-api-python-client`
  (Gmail API), `boto3` (SES), `flask` (unsubscribe server)
- `unittest`

---

## 🎯 Learning Objectives

- Python automation
- File handling and CSV validation
- Modular programming
- Environment variable management
- Email automation with proper security hygiene
- Error handling and exit codes
- Logging and reporting
- Batch scripting and Windows Task Scheduler
- Professional project organization

---

## 🔮 Future Improvements

- Docker deployment
- Email scheduling UI
- Database-backed suppression list (shared across machines)
- Real-time ESP webhooks for bounce events

> Already implemented in this version: Gmail API / SendGrid / SES
> backends, retry queue with reconnect, auto-resume (`--resume`),
> CLI arguments, unsubscribe links with one-click (RFC 8058) support,
> and bounce processing.

---

## 📜 License

This project is licensed under the MIT License.
