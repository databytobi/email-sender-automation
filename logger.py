import logging
import logging.handlers
from email.utils import parseaddr
from pathlib import Path

# Anchor the logs folder to the project directory, so it does not matter
# which working directory the script is launched from.
BASE_DIR = Path(__file__).parent
LOG_FOLDER = BASE_DIR / "logs"
LOG_FOLDER.mkdir(exist_ok=True)

logger = logging.getLogger("email_automation")
logger.setLevel(logging.INFO)

# Prevent duplicate handlers if imported multiple times
if not logger.handlers:
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Rotating file handler keeps the log bounded instead of growing forever.
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FOLDER / "automation.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler for warnings/errors only: the tqdm progress bar and
    # the printed summary stay readable while problems remain visible.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console_handler)


def mask_email(email):
    """Return a privacy-safe representation of an email address for logs.

    Example: "tomwalkertom12@gmail.com" -> "t***@gmail.com"
    The delivery report still contains full addresses (needed for
    operations); logs do not need them.
    """
    parsed = parseaddr(str(email))[1]
    local, separator, domain = parsed.partition("@")

    if not separator or not local or not domain:
        return "***"

    return f"{local[0]}***@{domain}"
