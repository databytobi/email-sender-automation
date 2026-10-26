import os
from email.utils import parseaddr
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ==========================================
# Email Credentials
# ==========================================

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# ==========================================
# SMTP Configuration
# ==========================================

SENDER_NAME = os.getenv("SENDER_NAME", "Olukunle.com")


SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")

try:
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
except (TypeError, ValueError):
    SMTP_PORT = None

# ==========================================
# Project Directories
# ==========================================

BASE_DIR = Path(__file__).parent

# Campaign settings can be overridden without editing the source code.
EMAIL_TYPE = os.getenv("EMAIL_TYPE", "welcome").strip().lower()
RECIPIENTS_FILE = BASE_DIR / os.getenv("RECIPIENTS_FILE", "recipients.csv")

TEMPLATES_FOLDER = BASE_DIR / "templates"
ATTACHMENTS_FOLDER = BASE_DIR / "attachments"
LOG_FOLDER = BASE_DIR / "logs"
REPORTS_FOLDER = BASE_DIR / "reports"

# ==========================================
# Delivery Backend (ESP architecture)
# ==========================================
# smtp = classic SMTP/STARTTLS (default)
# gmail = Gmail API with OAuth2 (no app password, bounce sync included)
# sendgrid = SendGrid v3 REST API (bulk-safe, bounce sync included)
# ses = Amazon SES v2 API (bulk-safe, suppression list sync included)

VALID_BACKENDS = ("smtp", "gmail", "sendgrid", "ses")
DELIVERY_BACKEND = os.getenv("DELIVERY_BACKEND", "smtp").strip().lower()

# SendGrid (https://app.sendgrid.com/settings/api_keys)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")

# Gmail API: OAuth client downloaded from Google Cloud Console
# (APIs & Services > Credentials > OAuth client ID, type "Desktop app")
GMAIL_CREDENTIALS_FILE = BASE_DIR / os.getenv(
    "GMAIL_CREDENTIALS_FILE", "client_secret.json"
)
GMAIL_TOKEN_FILE = BASE_DIR / os.getenv("GMAIL_TOKEN_FILE", "gmail_token.json")

# Amazon SES (FromEmailAddress must be a verified identity)
AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip()
SES_FROM_ADDRESS = os.getenv("SES_FROM_ADDRESS")

# ==========================================
# Unsubscribe / Suppression
# ==========================================
# HMAC secret for unsubscribe tokens. Generate one with:
#   python -c "import secrets; print(secrets.token_hex(32))"
UNSUBSCRIBE_SECRET = os.getenv("UNSUBSCRIBE_SECRET", "").strip()

# HTTPS endpoint of the unsubscribe app (see unsubscribe_server.py).
# Enables RFC 8058 one-click unsubscribe in Gmail.
UNSUBSCRIBE_BASE_URL = os.getenv("UNSUBSCRIBE_BASE_URL", "").strip()

# mailto: fallback — works without hosting any server.
UNSUBSCRIBE_MAILTO = os.getenv("UNSUBSCRIBE_MAILTO", "").strip()

# Addresses listed here are never emailed (bounces, complaints,
# unsubscribes). Gitignored on purpose.
SUPPRESSION_FILE = BASE_DIR / os.getenv("SUPPRESSION_FILE", "suppression.csv")

# Per-campaign registries of successfully-sent addresses, used by
# --resume after a crashed/interrupted run. Gitignored on purpose.
STATE_FOLDER = BASE_DIR / os.getenv("STATE_FOLDER", "state")

# ==========================================
# Templates
# ==========================================
EMAIL_CONFIG = {
    "welcome": {
        "subject": "Welcome to Python Automation",
        "text_template": TEMPLATES_FOLDER / "welcome.txt",
        "html_template": TEMPLATES_FOLDER / "welcome.html",
        "attachments": [],
    },

    "invoice": {
        "subject": "Your Invoice",
        "text_template": TEMPLATES_FOLDER / "invoice.txt",
        "html_template": TEMPLATES_FOLDER / "invoice.html",
        "attachments": [
            ATTACHMENTS_FOLDER / "invoice.pdf",
            ATTACHMENTS_FOLDER / "certificate.pdf",
        ],
    },

    "certificate": {
        "subject": "Course Completion Certificate",
        "text_template": TEMPLATES_FOLDER / "certificate.txt",
        "html_template": TEMPLATES_FOLDER / "certificate.html",
        "attachments": [
            ATTACHMENTS_FOLDER / "certificate.pdf",
        ],
    },

    "newsletter": {
        "subject": "Weekly Newsletter",
        "text_template": TEMPLATES_FOLDER / "newsletter.txt",
        "html_template": TEMPLATES_FOLDER / "newsletter.html",
        "attachments": [
            ATTACHMENTS_FOLDER / "newsletter.pdf",
        ],
    },
}


def unsubscribe_settings():
    """Return the active unsubscribe configuration, or None if disabled.

    A usable unsubscribe setup needs the HMAC secret plus at least one
    target (HTTPS link or mailto address).
    """
    if not UNSUBSCRIBE_SECRET:
        return None

    if not UNSUBSCRIBE_BASE_URL and not UNSUBSCRIBE_MAILTO:
        return None

    return {
        "secret": UNSUBSCRIBE_SECRET,
        "base_url": UNSUBSCRIBE_BASE_URL,
        "mailto": UNSUBSCRIBE_MAILTO,
    }


def validate_configuration(email_type=None, check_credentials=True, backend=None):
    """Validate required settings and files before starting a campaign.

    Only the selected email type is validated, so a broken campaign
    cannot block unrelated ones.

    Args:
        email_type: The campaign type to validate. Defaults to EMAIL_TYPE.
        check_credentials: Set to False for dry runs, which do not
            connect to the delivery backend.
        backend: Delivery backend to validate. Defaults to DELIVERY_BACKEND.

    Raises:
        ValueError: If one or more configuration values are invalid.
    """
    if email_type is None:
        email_type = EMAIL_TYPE

    if backend is None:
        backend = DELIVERY_BACKEND

    if email_type not in EMAIL_CONFIG:
        raise ValueError(
            f"EMAIL_TYPE must be one of {', '.join(sorted(EMAIL_CONFIG))} "
            f"(got {email_type!r})"
        )

    if backend not in VALID_BACKENDS:
        raise ValueError(
            f"DELIVERY_BACKEND must be one of {', '.join(VALID_BACKENDS)} "
            f"(got {backend!r})"
        )

    errors = []

    if check_credentials:
        if backend == "smtp":
            if not EMAIL_ADDRESS:
                errors.append("EMAIL_ADDRESS is not set")
            else:
                _, parsed_address = parseaddr(EMAIL_ADDRESS)
                if not parsed_address or "@" not in parsed_address:
                    errors.append("EMAIL_ADDRESS is not a valid email address")

            if not EMAIL_PASSWORD:
                errors.append("EMAIL_PASSWORD is not set")

            if not SMTP_SERVER or not SMTP_SERVER.strip():
                errors.append("SMTP_SERVER is not set")

            if not isinstance(SMTP_PORT, int) or not 1 <= SMTP_PORT <= 65535:
                errors.append("SMTP_PORT must be an integer between 1 and 65535")

        elif backend == "gmail":
            if not GMAIL_CREDENTIALS_FILE.is_file():
                errors.append(
                    "GMAIL_CREDENTIALS_FILE does not exist: "
                    f"{GMAIL_CREDENTIALS_FILE} — download the OAuth client "
                    "from Google Cloud Console (type: Desktop app)"
                )

        elif backend == "sendgrid":
            if not SENDGRID_API_KEY:
                errors.append("SENDGRID_API_KEY is not set")

            if not EMAIL_ADDRESS:
                errors.append(
                    "EMAIL_ADDRESS is not set (used as the SendGrid From "
                    "sender — must be a verified sender in SendGrid)"
                )

        elif backend == "ses":
            if not SES_FROM_ADDRESS:
                errors.append("SES_FROM_ADDRESS is not set (must be a verified SES identity)")

            if not AWS_REGION:
                errors.append("AWS_REGION is not set")

    email_config = EMAIL_CONFIG[email_type]

    for key in ("subject", "text_template", "html_template", "attachments"):
        if key not in email_config:
            errors.append(f"{email_type}: missing '{key}' configuration")

    if not email_config.get("subject"):
        errors.append(f"{email_type}: subject is empty")

    for template_key in ("text_template", "html_template"):
        template_path = email_config.get(template_key)
        if not template_path or not Path(template_path).is_file():
            errors.append(
                f"{email_type}: {template_key} does not exist: {template_path}"
            )

    for attachment_path in email_config.get("attachments", []):
        if not Path(attachment_path).is_file():
            errors.append(
                f"{email_type}: attachment does not exist: {attachment_path}"
            )

    if errors:
        raise ValueError(
            "Configuration validation failed:\n- " + "\n- ".join(errors)
        )
