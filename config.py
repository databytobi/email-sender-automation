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


def validate_configuration(email_type=None, check_credentials=True):
    """Validate required settings and files before starting a campaign.

    Only the selected email type is validated, so a broken campaign
    cannot block unrelated ones.

    Args:
        email_type: The campaign type to validate. Defaults to EMAIL_TYPE.
        check_credentials: Set to False for dry runs, which do not
            connect to the SMTP server.

    Raises:
        ValueError: If one or more configuration values are invalid.
    """
    if email_type is None:
        email_type = EMAIL_TYPE

    if email_type not in EMAIL_CONFIG:
        raise ValueError(
            f"EMAIL_TYPE must be one of {', '.join(sorted(EMAIL_CONFIG))} "
            f"(got {email_type!r})"
        )

    errors = []

    if check_credentials:
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
