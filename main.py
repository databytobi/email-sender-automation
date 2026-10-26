import argparse
import sys
import time
from html import escape

from tqdm import tqdm

from config import (
    DELIVERY_BACKEND,
    EMAIL_CONFIG,
    EMAIL_TYPE,
    RECIPIENTS_FILE,
    REPORTS_FOLDER,
    SUPPRESSION_FILE,
    VALID_BACKENDS,
    unsubscribe_settings,
    validate_configuration,
)
from loaders.recipient_loader import read_recipients
from loaders.template_loader import read_template
from logger import logger, mask_email
from providers import create_delivery_provider
from providers.base import (
    AuthDeliveryError,
    EmailPayload,
    RetryableDeliveryError,
)
from reports.report_generator import save_report
from state import clear_sent_registry, load_sent_registry, record_sent
from suppression import import_bounce_file, load_suppression, merge_bounces
from unsubscribe import (
    append_footer,
    build_mailto_link,
    build_unsubscribe_headers,
    build_unsubscribe_link,
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
    parser.add_argument(
        "--backend",
        choices=VALID_BACKENDS,
        default=DELIVERY_BACKEND,
        help=f"delivery backend (default: {DELIVERY_BACKEND}); "
        "sendgrid/ses/gmail are the bulk-safe ESP options",
    )
    parser.add_argument(
        "--no-unsubscribe",
        action="store_true",
        help="do not add the unsubscribe footer and List-Unsubscribe headers "
        "(transactional/one-to-one mail only)",
    )
    parser.add_argument(
        "--sync-bounces",
        action="store_true",
        help="pull bounces from the delivery backend into the suppression "
        "list, then exit (no campaign is sent)",
    )
    parser.add_argument(
        "--import-bounces",
        metavar="FILE",
        help="import bounced addresses from a CSV (Email column) or "
        "one-address-per-line text file into the suppression list, then exit",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip recipients already successfully sent in a previous run "
        "of this campaign type (use after a crashed or interrupted run)",
    )
    parser.add_argument(
        "--reset-sent",
        action="store_true",
        help="delete the sent registry for the selected campaign type "
        "(use before an intentional re-send), then exit",
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


def confirm_campaign(recipients, campaign, args, already_sent_count=0):
    """Ask for an explicit confirmation before a live campaign.

    Returns:
        bool: True if the campaign should proceed.
    """
    print("\n" + "=" * 60)
    print("⚠  LIVE CAMPAIGN READY — emails will be sent")
    print("=" * 60)
    print(f"Campaign type : {args.email_type}")
    print(f"Backend       : {args.backend}")
    print(f"Subject       : {campaign['subject']}")
    print(f"Recipients    : {len(recipients)}")

    if args.resume:
        print(
            f"Resume        : on ({already_sent_count} address(es) already "
            "sent will be skipped)"
        )

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


def render_bodies(campaign, recipient, text_template, html_template, unsubscribe):
    """Render the plain-text and HTML bodies for one recipient.

    CSV values are HTML-escaped before going into the HTML template,
    so a crafted name (e.g. "<script>...") cannot inject markup into
    the email. The unsubscribe footer and List-Unsubscribe headers are
    attached when an unsubscribe setup is configured.
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

    headers = {}

    if unsubscribe:
        https_link = None
        mailto_link = None

        if unsubscribe["base_url"]:
            https_link = build_unsubscribe_link(
                recipient["Email"],
                unsubscribe["base_url"],
                unsubscribe["secret"],
            )

        if unsubscribe["mailto"]:
            mailto_link = build_mailto_link(
                recipient["Email"], unsubscribe["mailto"], unsubscribe["secret"]
            )

        text_body, html_body = append_footer(
            text_body, html_body, https_link, mailto_link
        )
        headers = build_unsubscribe_headers(https_link, mailto_link)

    return text_body, html_body, headers


def run_bounce_sync(backend):
    """Pull bounces from the delivery backend into the suppression list."""
    provider = create_delivery_provider(backend)

    if not provider.supports_bounce_sync:
        provider.fetch_bounces()
        print(
            f"The {backend} backend cannot sync bounces automatically."
        )
        return 0

    provider.connect()

    bounces = provider.fetch_bounces()

    provider.close()

    added = merge_bounces(SUPPRESSION_FILE, bounces, source=f"{backend}-sync")

    print(f"Synced {len(bounces)} bounce(s) from {backend}; "
          f"{added} new address(es) added to {SUPPRESSION_FILE}.")

    return 0


def run_bounce_import(file_path):
    """Import bounced addresses from a file into the suppression list."""
    try:
        added = import_bounce_file(file_path, SUPPRESSION_FILE)
    except FileNotFoundError:
        print(f"Bounce import file not found: {file_path}")
        return 1

    print(f"Imported bounces from {file_path}; "
          f"{added} new address(es) added to {SUPPRESSION_FILE}.")

    return 0


def run_sent_registry_reset(campaign):
    """Delete the sent registry for a campaign type."""
    removed = clear_sent_registry(campaign)

    if removed:
        print(f"Removed sent registry for campaign '{campaign}'.")
    else:
        print(f"No sent registry exists for campaign '{campaign}' — "
              "nothing to remove.")

    return 0


def print_summary(args, report, successful, failed, suppressed, resumed, duration):
    total = len(report)
    attempted = successful + failed

    success_rate = (successful / attempted) * 100 if attempted else 0

    print("\n" + "=" * 60)
    print("📊 EMAIL AUTOMATION SUMMARY")
    print("=" * 60)

    print(f"Mode             : {'Dry-run' if args.dry_run else 'Live'}")
    print(f"Backend          : {args.backend}")
    print(f"Campaign type    : {args.email_type}")
    print(f"Total Recipients : {total}")
    print(f"Suppressed       : {suppressed} (skipped, on suppression list)")

    if args.resume:
        print(f"Already sent     : {resumed} (skipped by --resume)")

    print(f"Attempted        : {attempted}")
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
            f"{'Status':<15}"
            f"{'Error'}"
        )

        print("-" * 100)

        for row in report:
            print(
                f"{row['Name']:<15}"
                f"{row['Email']:<35}"
                f"{row['Status']:<15}"
                f"{row['Error']}"
            )


def main(argv=None):
    _ensure_utf8_output()

    args = build_argument_parser().parse_args(argv)

    # -- Standalone maintenance operations (no campaign is sent).
    if args.sync_bounces:
        try:
            return run_bounce_sync(args.backend)
        except AuthDeliveryError as error:
            print(f"\n❌ {error}")
            return 2

    if args.import_bounces:
        return run_bounce_import(args.import_bounces)

    if args.reset_sent:
        return run_sent_registry_reset(args.email_type)

    # -- Dry-run mode does not need credentials, only campaign files.
    try:
        validate_configuration(
            email_type=args.email_type,
            check_credentials=not args.dry_run,
            backend=args.backend,
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

    # -- Unsubscribe setup (CAN-SPAM/GDPR requirement for bulk mail).
    unsubscribe = None if args.no_unsubscribe else unsubscribe_settings()

    if not args.dry_run and unsubscribe is None and not args.no_unsubscribe:
        print(
            "\n⚠  WARNING: no unsubscribe configuration found. Bulk email "
            "without an unsubscribe option violates CAN-SPAM/GDPR. "
            "Set UNSUBSCRIBE_SECRET plus UNSUBSCRIBE_BASE_URL (one-click) "
            "and/or UNSUBSCRIBE_MAILTO in your .env."
        )
        logger.warning("Live campaign started without unsubscribe support.")

    # -- Suppression list: never email these addresses again.
    suppression = load_suppression(SUPPRESSION_FILE)

    # -- Sent registry: addresses already successfully sent for this
    # campaign type. Loaded always (so live runs never write duplicates
    # to the file), but only used for skipping when --resume is set.
    already_sent = load_sent_registry(args.email_type)

    if args.resume and already_sent:
        logger.info(
            f"Resume mode: {len(already_sent)} address(es) already sent "
            f"for campaign '{args.email_type}'"
        )
    elif args.resume:
        print(
            f"Note: --resume requested, but the sent registry for "
            f"'{args.email_type}' is empty — sending to everyone."
        )

    logger.info(
        f"Starting email automation "
        f"({'dry-run' if args.dry_run else 'live'}, backend={args.backend}, "
        f"type={args.email_type}, recipients={len(recipients)}, "
        f"suppressed={len(suppression)}, "
        f"already_sent={len(already_sent)})"
    )

    if not args.dry_run and not args.yes:
        if not confirm_campaign(
            recipients, campaign, args, already_sent_count=len(already_sent)
        ):
            logger.warning("Campaign aborted by user before sending.")
            print("Campaign aborted before sending.")
            return 1

    start_time = time.time()

    report = []
    successful = 0
    failed = 0
    suppressed = 0
    resumed = 0

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

    provider = None
    exit_code = None

    try:
        # One authenticated session for the whole campaign, reused for
        # every recipient (SMTP connection, SendGrid HTTP session,
        # Gmail/SES API client).
        if not args.dry_run:
            provider = create_delivery_provider(args.backend)
            provider.connect()

        for recipient in progress:

            progress.set_postfix(recipient=recipient["Name"])

            # Never email suppressed addresses (bounces, complaints,
            # past unsubscribes).
            if recipient["Email"].lower() in suppression:
                suppressed += 1
                report.append(
                    {
                        "Name": recipient["Name"],
                        "Email": recipient["Email"],
                        "Status": "Suppressed",
                        "Error": "On suppression list",
                    }
                )
                logger.info(
                    f"Skipping suppressed recipient "
                    f"{mask_email(recipient['Email'])}"
                )
                continue

            # Resume mode: skip addresses already sent in a previous
            # run of this campaign type.
            if args.resume and recipient["Email"].lower() in already_sent:
                resumed += 1
                report.append(
                    {
                        "Name": recipient["Name"],
                        "Email": recipient["Email"],
                        "Status": "Already sent",
                        "Error": "Skipped by --resume",
                    }
                )
                logger.info(
                    f"Skipping already-sent recipient "
                    f"{mask_email(recipient['Email'])} (--resume)"
                )
                continue

            try:
                text_body, html_body, headers = render_bodies(
                    campaign, recipient, text_template, html_template, unsubscribe
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
                f"({mask_email(recipient['Email'])}) via {args.backend}..."
            )

            payload = EmailPayload(
                to_email=recipient["Email"],
                subject=campaign["subject"],
                text_body=text_body,
                html_body=html_body,
                attachment_paths=campaign["attachments"],
                extra_headers=headers,
                # SendGrid passes these through to webhook events, so
                # bounces can be attributed to this campaign later.
                custom_args={"campaign": args.email_type},
            )

            if args.dry_run:
                result = {"success": True, "error": None, "message_id": None}
            else:
                # Reconnect once if the session drops mid-campaign
                # instead of marking the recipient as permanently failed.
                attempts = 2

                while True:
                    try:
                        result = provider.send(payload)
                        break
                    except RetryableDeliveryError as error:
                        if attempts > 1:
                            attempts -= 1
                            logger.warning(
                                f"Reconnecting to {args.backend} after: {error}"
                            )
                            provider.reconnect()
                        else:
                            result = {
                                "success": False,
                                "error": f"Connection lost after retry: {error}",
                                "message_id": None,
                            }
                            break

            if result["success"]:
                successful += 1

                # Record the send the moment it succeeds so a crash
                # right after still leaves it resumable. Never during
                # dry runs. The in-memory set prevents duplicate rows
                # on intentional re-sends.
                if not args.dry_run:
                    email_key = recipient["Email"].lower()

                    if email_key not in already_sent:
                        record_sent(
                            args.email_type,
                            recipient["Email"],
                            backend=args.backend,
                            message_id=result.get("message_id") or "",
                        )
                        already_sent.add(email_key)
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

    except AuthDeliveryError as error:
        # Wrong credentials: abort the whole campaign instead of
        # hammering the provider for every remaining recipient.
        logger.error(str(error))
        print(f"\n❌ {error}")
        print("Campaign aborted — fix the backend credentials and re-run.")
        exit_code = 2

    except KeyboardInterrupt:
        logger.warning("Campaign aborted by user (Ctrl+C).")
        print("\n\nAborted by user (Ctrl+C). Partial report saved.")
        exit_code = 130

    finally:
        progress.close()

        if provider is not None:
            try:
                provider.close()
            except Exception:
                logger.warning("Could not close the delivery session cleanly.")

    duration = time.time() - start_time

    print_summary(args, report, successful, failed, suppressed, resumed, duration)

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
