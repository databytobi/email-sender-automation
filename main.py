import argparse
import smtplib
import sys
import time
from html import escape

from tqdm import tqdm

from config import (
    EMAIL_CONFIG,
    EMAIL_TYPE,
    RECIPIENTS_FILE,
    REPORTS_FOLDER,
    validate_configuration,
)
from loaders.recipient_loader import read_recipients
from loaders.template_loader import read_template
from logger import logger, mask_email
from reports.report_generator import save_report
from sender import SMTPAuthError, connect_smtp, send_email


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Send a personalized email campaign from a CSV recipient list.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="render the emails and produce a report without sending anything",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="skip the confirmation prompt (required for non-interactive runs, "
        "e.g. Windows Task Scheduler)",
    )
    parser.add_argument(
        "--type",
        dest="email_type",
        choices=sorted(EMAIL_CONFIG),
        default=EMAIL_TYPE,
        help=f"campaign type to send (default: {EMAIL_TYPE})",
    )
    parser.add_argument(
        "--recipients",
        default=str(RECIPIENTS_FILE),
        help="path to the recipients CSV file",
    )

    return parser


def _build_context(recipient):
    """Build a case-insensitive placeholder context from a recipient row.

    Both {Name} and {name} style placeholders resolve to the same CSV
    column, so the stock templates ({name}) and custom CSV columns
    ({Company}, {company}, ...) all work.
    """
    context = dict(recipient)

    for key, value in recipient.items():
        lower_key = key.lower()
        if lower_key not in context:
            context[lower_key] = value

    return context


def personalize(template, recipient, template_path):
    """Render a template using the recipient's CSV columns as placeholders.

    Raises a clear error instead of a raw KeyError/ValueError when a
    template contains a placeholder that is not a CSV column.
    """
    try:
        return template.format(**_build_context(recipient))
    except (KeyError, IndexError, ValueError) as error:
        raise ValueError(
            f"Could not render {template_path}: {error!r}. "
            f"Available columns: {', '.join(recipient)}"
        ) from error


def confirm_campaign(recipients, campaign, email_type):
    """Ask for an explicit confirmation before a live campaign.

    Returns:
        bool: True if the campaign should proceed.
    """
    print("\n" + "=" * 60)
    print("⚠  LIVE CAMPAIGN READY — emails will be sent")
    print("=" * 60)
    print(f"Campaign type : {email_type}")
    print(f"Subject       : {campaign['subject']}")
    print(f"Recipients    : {len(recipients)}")
    print("=" * 60)

    # Scheduled tasks have no interactive stdin: refuse instead of
    # hanging forever on a prompt nobody can answer.
    if not sys.stdin.isatty():
        print(
            "\nRefusing to send without confirmation in a non-interactive "
            "session. Re-run with --yes to confirm on the command line."
        )
        return False

    try:
        reply = input("\nProceed? Type YES to continue: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        # No answer available (closed stdin, Ctrl+C, etc.) = not confirmed.
        return False

    return reply == "yes"


def render_bodies(campaign, recipient, text_template, html_template):
    """Render the plain-text and HTML bodies for one recipient.

    CSV values are HTML-escaped before going into the HTML template,
    so a crafted name (e.g. "<script>...") cannot inject markup into
    the email.
    """
    text_body = personalize(
        text_template, recipient, campaign["text_template"]
    )

    html_context = {
        key: escape(value) if isinstance(value, str) else value
        for key, value in recipient.items()
    }
    html_body = personalize(
        html_template, html_context, campaign["html_template"]
    )

    return text_body, html_body


def print_summary(args, report, successful, failed, duration):
    total = len(report)

    success_rate = (successful / total) * 100 if total else 0

    print("\n" + "=" * 60)
    print("📊 EMAIL AUTOMATION SUMMARY")
    print("=" * 60)

    print(f"Mode             : {'Dry-run' if args.dry_run else 'Live'}")
    print(f"Campaign type    : {args.email_type}")
    print(f"Total Recipients : {total}")
    print(f"Successful       : {successful}")
    print(f"Failed           : {failed}")
    print(f"Success Rate     : {success_rate:.2f}%")
    print(f"Duration         : {duration:.2f} seconds")

    print("=" * 60)

    if report:
        print("\n📋 EMAIL DELIVERY REPORT")
        print("=" * 100)

        print(
            f"{'Name':<15}"
            f"{'Email':<35}"
            f"{'Status':<12}"
            f"{'Error'}"
        )

        print("-" * 100)

        for row in report:
            print(
                f"{row['Name']:<15}"
                f"{row['Email']:<35}"
                f"{row['Status']:<12}"
                f"{row['Error']}"
            )


def _ensure_utf8_output():
    """Make redirected output safe on Windows.

    When stdout is a real console, Python already uses UTF-8 (or the
    console API). When it is redirected — scheduled tasks, CI, `>` file
    capture — Windows defaults to a legacy code page (cp1252), which
    cannot encode the emoji used in the progress bar and summary, and
    crashes the run. Reconfigure to UTF-8 with replacement errors.
    """
    encoding = (sys.stdout.encoding or "").lower().replace("-", "")

    if encoding != "utf8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # Non-standard streams: keep as-is.
            pass


def main(argv=None):
    _ensure_utf8_output()

    args = build_argument_parser().parse_args(argv)

    # -- Dry-run mode does not need credentials, only campaign files.
    try:
        validate_configuration(
            email_type=args.email_type,
            check_credentials=not args.dry_run,
        )
    except ValueError as error:
        logger.error(str(error))
        print(f"Configuration error:\n{error}")
        return 1

    campaign = EMAIL_CONFIG[args.email_type]

    try:
        recipients = read_recipients(args.recipients)
    except FileNotFoundError:
        logger.error(f"Recipients file not found: {args.recipients}")
        print(f"Recipients file not found: {args.recipients}")
        return 1
    except ValueError as error:
        logger.error(str(error))
        print(f"Recipients error: {error}")
        return 1

    if not recipients:
        print(f"No recipients found in {args.recipients} — nothing to do.")
        return 1

    logger.info(
        f"Starting email automation "
        f"({'dry-run' if args.dry_run else 'live'}, type={args.email_type}, "
        f"recipients={len(recipients)})"
    )

    if not args.dry_run and not args.yes:
        if not confirm_campaign(recipients, campaign, args.email_type):
            logger.warning("Campaign aborted by user before sending.")
            print("Campaign aborted before sending.")
            return 1

    start_time = time.time()

    report = []
    successful = 0
    failed = 0

    text_template = read_template(campaign["text_template"])
    html_template = read_template(campaign["html_template"])

    # Progress bar on stdout; logging warnings go to stderr.
    progress = tqdm(
        recipients,
        desc="📧 Email Campaign",
        unit="email",
        colour="green",
        file=sys.stdout,
    )

    smtp = None
    exit_code = None

    try:
        # One connection for the whole campaign instead of one per email.
        if not args.dry_run:
            smtp = connect_smtp()

        for recipient in progress:

            progress.set_postfix(recipient=recipient["Name"])

            try:
                text_body, html_body = render_bodies(
                    campaign, recipient, text_template, html_template
                )
            except ValueError as error:
                logger.error(str(error))
                failed += 1
                report.append(
                    {
                        "Name": recipient["Name"],
                        "Email": recipient["Email"],
                        "Status": "Failed",
                        "Error": str(error),
                    }
                )
                continue

            logger.info(
                f"Sending email to {recipient['Name']} "
                f"({mask_email(recipient['Email'])})..."
            )

            if args.dry_run:
                result = {"success": True, "error": None}
            else:
                # Reconnect once if the connection drops mid-campaign
                # instead of marking the recipient as permanently failed.
                attempts = 2

                while True:
                    try:
                        result = send_email(
                            smtp,
                            recipient_email=recipient["Email"],
                            subject=campaign["subject"],
                            text_body=text_body,
                            html_body=html_body,
                            attachment_paths=campaign["attachments"],
                        )
                        break
                    except smtplib.SMTPServerDisconnected:
                        if attempts > 1:
                            attempts -= 1
                            logger.warning("Reconnecting to the SMTP server...")
                            smtp = connect_smtp()
                        else:
                            result = {
                                "success": False,
                                "error": "SMTP server disconnected",
                            }
                            break

            if result["success"]:
                successful += 1
            else:
                failed += 1

            status = (
                "Dry-run"
                if args.dry_run
                else ("Sent" if result["success"] else "Failed")
            )

            report.append(
                {
                    "Name": recipient["Name"],
                    "Email": recipient["Email"],
                    "Status": status,
                    "Error": result["error"] or "-",
                }
            )

            progress.set_postfix(
                recipient=recipient["Name"],
                sent=successful,
                failed=failed,
            )

            logger.info(f"Finished processing {recipient['Name']}")

    except SMTPAuthError as error:
        # Wrong credentials: abort the whole campaign instead of
        # hammering the server for every remaining recipient.
        logger.error(str(error))
        print(f"\n❌ {error}")
        print("Campaign aborted — fix EMAIL_ADDRESS / EMAIL_PASSWORD and re-run.")
        exit_code = 2

    except smtplib.SMTPException as error:
        logger.error(f"Could not connect to the SMTP server: {error}")
        print(f"\n❌ Could not connect to the SMTP server: {error}")
        exit_code = 2

    except KeyboardInterrupt:
        logger.warning("Campaign aborted by user (Ctrl+C).")
        print("\n\nAborted by user (Ctrl+C). Partial report saved.")
        exit_code = 130

    finally:
        progress.close()

        if smtp:
            try:
                smtp.quit()
            except Exception:
                logger.warning("Could not close the SMTP connection cleanly.")

    duration = time.time() - start_time

    print_summary(args, report, successful, failed, duration)

    # Timestamped report so previous campaigns are never overwritten.
    report_path = REPORTS_FOLDER / (
        f"email_report_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    )

    if report:
        save_report(report, report_path)
        logger.info(f"Delivery report saved to {report_path}")
        print(f"\n💾 Delivery report saved to: {report_path}")

    if exit_code is not None:
        return exit_code

    if failed:
        logger.info("Email automation completed with failures.")
        return 1

    logger.info("Email automation completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
