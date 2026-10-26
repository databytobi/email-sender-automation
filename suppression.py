"""Suppression list management.

A simple, gitignored CSV keeps every address that must never receive
mail again: bounced addresses, spam complaints, and unsubscribe
requests. The sender checks this list before every campaign.

Format: Email, Reason, Source, Date
"""

import csv
from datetime import datetime
from pathlib import Path

from logger import logger

FIELDS = ["Email", "Reason", "Source", "Date"]


def load_suppression(file_path):
    """Load the suppression list as {lowercased email: row}."""
    path = Path(file_path)

    if not path.is_file():
        return {}

    suppressed = {}

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            email = (row.get("Email") or "").strip()
            if email:
                suppressed[email.lower()] = row

    return suppressed


def add_to_suppression(file_path, email, reason, source="manual"):
    """Add an address to the suppression list (idempotent).

    Returns:
        bool: True if the address was added, False if it was already
            present.
    """
    path = Path(file_path)
    email = email.strip()

    if not email:
        return False

    existing = load_suppression(path)

    if email.lower() in existing:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)

    new_file = not path.is_file()

    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "Email": email,
                "Reason": reason,
                "Source": source,
                "Date": datetime.now().strftime("%Y-%m-%d"),
            }
        )

    logger.info(f"Suppressed {email} ({reason})")

    return True


def merge_bounces(file_path, bounces, source="bounce-sync"):
    """Merge bounce dicts from a provider into the suppression list.

    Args:
        bounces: list of dicts with keys 'email' and optionally
            'reason' and 'date'.

    Returns:
        int: Number of newly suppressed addresses.
    """
    added = 0

    for bounce in bounces:
        email = (bounce.get("email") or "").strip()
        if not email:
            continue

        reason = bounce.get("reason") or "bounced"

        if add_to_suppression(file_path, email, reason, source=source):
            added += 1

    return added


def import_bounce_file(file_path, suppression_path, source="import"):
    """Import bounced addresses from a CSV or plain-text file.

    Accepts either:
    - a CSV with an Email column (Reason/Date columns optional), or
    - one email address per line.

    Returns:
        int: Number of newly suppressed addresses.
    """
    path = Path(file_path)
    bounces = []

    if path.suffix.lower() == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                email = (row.get("Email") or row.get("email") or "").strip()
                if email:
                    bounces.append(
                        {
                            "email": email,
                            "reason": row.get("Reason") or "bounced",
                        }
                    )
    else:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            email = line.strip()
            if email and "@" in email:
                bounces.append({"email": email, "reason": "bounced"})

    return merge_bounces(suppression_path, bounces, source=source)
