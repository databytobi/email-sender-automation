import csv

from logger import logger

REQUIRED_COLUMNS = ("Name", "Email")


def read_recipients(file_path):
    """
    Read recipients from a CSV file.

    Validates required columns, strips whitespace, skips blank rows,
    and skips duplicate email addresses (case-insensitive).

    Returns:
        list[dict]: A list of recipients.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is empty, is missing required columns,
            or a row is missing a name or email.
    """
    recipients = []
    seen_emails = set()

    # utf-8-sig transparently handles CSV files saved by Excel (BOM).
    with open(file_path, mode="r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(f"Recipients file is empty: {file_path}")

        fieldnames = [name.strip() for name in reader.fieldnames]
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]

        if missing:
            raise ValueError(
                f"Recipients file is missing required column(s): "
                f"{', '.join(missing)} (found: {', '.join(fieldnames)})"
            )

        for line_number, row in enumerate(reader, start=2):
            cleaned = {
                key: (value or "").strip()
                for key, value in row.items()
                if key is not None
            }

            # Skip completely blank rows (trailing newlines, empty lines).
            if not any(cleaned.values()):
                continue

            name = cleaned.get("Name", "")
            email = cleaned.get("Email", "")

            if not email:
                raise ValueError(
                    f"Row {line_number} of {file_path} is missing an Email"
                )

            if not name:
                raise ValueError(
                    f"Row {line_number} of {file_path} is missing a Name"
                )

            email_key = email.lower()

            if email_key in seen_emails:
                logger.warning(
                    f"Skipping duplicate email on line {line_number}: {email}"
                )
                continue

            seen_emails.add(email_key)
            recipients.append(cleaned)

    return recipients


def write_recipients(file_path, recipients):
    """Write a recipients list back to a CSV file.

    Used by the web UI to persist add/remove operations. Column order
    from the first row is preserved; recipients missing a column are
    written with an empty value.

    Args:
        recipients: List of dicts with at least the Name and Email keys.
    """
    from logger import logger

    fieldnames = None

    for recipient in recipients:
        if fieldnames is None:
            fieldnames = list(recipient.keys())
        else:
            for key in recipient.keys():
                if key not in fieldnames:
                    fieldnames.append(key)

    if fieldnames is None:
        fieldnames = list(REQUIRED_COLUMNS)

    for column in REQUIRED_COLUMNS:
        if column not in fieldnames:
            fieldnames.insert(0, column)

    with open(file_path, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()

        for recipient in recipients:
            row = {key: recipient.get(key, "") for key in fieldnames}
            writer.writerow(row)

    logger.info(f"Saved {len(recipients)} recipient(s) to {file_path}")
