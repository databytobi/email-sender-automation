"""Sent-state tracking for auto-resume.

Live sends are recorded in a per-campaign registry,
``state/sent_<campaign>.csv``::

    Email, Date, Backend, MessageId

The row is appended immediately after each successful send (never
during dry runs), so a crash right after a send still leaves the
address recorded. Re-running with ``--resume`` skips registered
addresses and continues the campaign where it stopped.

The registry is keyed per campaign type (not per backend), so
switching backends mid-campaign still resumes correctly.
"""

import csv
from datetime import datetime

from config import STATE_FOLDER

FIELDS = ["Email", "Date", "Backend", "MessageId"]


def sent_registry_path(campaign):
    """Return the registry file path for a campaign type."""
    return STATE_FOLDER / f"sent_{campaign}.csv"


def load_sent_registry(campaign):
    """Load all addresses successfully sent for a campaign type.

    Returns:
        set[str]: Lowercased email addresses.
    """
    path = sent_registry_path(campaign)

    if not path.is_file():
        return set()

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return {
            (row.get("Email") or "").strip().lower()
            for row in csv.DictReader(file)
            if (row.get("Email") or "").strip()
        }


def record_sent(campaign, email, backend="", message_id=""):
    """Append one successfully-sent address to the registry.

    The write is flushed before returning, so the record survives a
    crash immediately after the send.
    """
    path = sent_registry_path(campaign)

    path.parent.mkdir(parents=True, exist_ok=True)

    new_file = not path.is_file()

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)

        if new_file:
            writer.writeheader()

        writer.writerow(
            {
                "Email": email,
                "Date": datetime.now().isoformat(timespec="seconds"),
                "Backend": backend,
                "MessageId": message_id or "",
            }
        )


def clear_sent_registry(campaign):
    """Delete the registry file for a campaign type.

    Use before an intentional re-send of the same campaign.

    Returns:
        bool: True if a registry existed and was removed.
    """
    path = sent_registry_path(campaign)

    if path.is_file():
        path.unlink()
        return True

    return False
