# 📧 Email Sender Automation

Python 3.10+ · MIT License · Status: Completed · PRs Welcome

A professional Python email automation system built for learning, teaching, and real-world automation.

This project demonstrates how to build a production-style email sender that supports personalized emails, HTML templates, attachments, logging, reporting, error handling, and Windows Task Scheduler integration.

---

## ✨ Features

- Send personalized emails from a CSV file
- Plain-text and HTML email support
- Multiple email templates and attachments
- **Dry-run mode** — preview a campaign without sending anything
- **Confirmation prompt** — a live campaign never sends without an explicit go-ahead
- One reusable SMTP connection per campaign (fast, avoids provider rate-limit flags)
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
├── reports/
│   ├── report_generator.py
│   └── email_report_YYYYMMDD_HHMMSS.csv   # generated per run
├── scripts/
│   └── run_email_automation.bat
├── templates/            # .txt + .html pairs, personalize with {Name} etc.
├── tests/                # unit tests (python -m unittest discover)
├── config.py
├── logger.py
├── main.py
├── sender.py
├── recipients.csv        # your recipient list (never commit real data)
├── recipients_example.csv
├── requirements.txt
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

> **Privacy:** `recipients.csv` and `.env` are gitignored on purpose.
> Real recipient data and credentials must never be committed.

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

## 📅 Scheduling (Windows Task Scheduler)

Use the included batch script. Non-interactive runs must pass `--yes`:

```
scripts\run_email_automation.bat --yes
```

The script locates the project relative to itself, uses the project venv when
available (falling back to system Python), passes arguments through, and
propagates the exit code so Task Scheduler can detect failures.

> **Bulk sending limits:** consumer Gmail accounts cap at ~500 recipients/day
> and flag bulk sending. For anything beyond a small list, use a dedicated
> ESP (SES, SendGrid, Mailgun). Also remember that commercial email must
> include an unsubscribe option (CAN-SPAM/GDPR).

---

## 🧪 Running the Tests

```bash
python -m unittest discover -v
```

The suite covers the recipient loader (validation, duplicates, BOM handling),
the sender (message construction, MIME types, header injection, reconnect
semantics), configuration validation, and the templates.

---

## 🛠 Technologies Used

- Python 3.10+
- `smtplib` + `email.message.EmailMessage`
- `ssl` (TLS with certificate validation)
- `python-dotenv`
- `tqdm`
- `logging` (rotating handlers)
- `pathlib`, `csv`, `argparse`, `mimetypes`
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

- Gmail API support
- SendGrid integration
- Docker deployment
- Email scheduling UI
- Retry queue
- Database support

> Already implemented in this version: CLI arguments, dry-run mode, and
> automatic reconnect-and-retry for dropped SMTP connections.

---

## 📜 License

This project is licensed under the MIT License.
