import csv
from pathlib import Path

REPORT_FIELDS = ["Name", "Email", "Status", "Error"]


def save_report(report, output_path):
    """
    Save the email delivery report to a CSV file.

    Args:
        report: List of dicts containing the keys in REPORT_FIELDS.
        output_path: Destination CSV path (parent folders are created
            if they do not exist).

    Returns:
        Path: The resolved path of the written report.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=REPORT_FIELDS,
        )

        writer.writeheader()
        writer.writerows(report)

    return output
