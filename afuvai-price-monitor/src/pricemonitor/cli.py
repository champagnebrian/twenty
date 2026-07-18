# argparse CLI for the price monitor ingestion paths (D6). Stdlib only.
# Subcommands:
#   parse-email       email body → proposal candidates (optionally appended to
#                     data/proposals.csv with status=proposed)
#   add-quote         manual quick-entry from a terminal → data/price-log.csv
#                     (Brian typing IS the confirmation, like the sheet)
#   merge-sheet       downloaded Quick Entry workbook/CSV → merge into the
#                     price log, then auto-confirm matching proposals and
#                     expire stale ones
#   expire-proposals  run just the confirm/expire pass (scheduled ingestion
#                     runs call this even when there is no sheet download)

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from pricemonitor.models import (
    CONFIG_DIR,
    DATA_DIR,
    PACKAGE_ROOT,
    ProposalRow,
    ValidationError,
    load_stems,
)
from pricemonitor.quote_parser import candidates_to_proposals, parse_quote_email
from pricemonitor.sheet_io import (
    QUICK_ENTRY_COLUMNS,
    merge_rows_into_price_log,
    parse_quick_entry_csv,
    parse_quick_entry_tab,
    quick_entry_entries_to_rows,
    read_price_log,
    read_proposals,
    write_proposals,
)

DEFAULT_EXPIRE_DAYS = 21


# --- Proposal lifecycle (the confirmation loop, D6/WS3) -------------------------

def _proposal_age_basis(proposal: ProposalRow) -> date | None:
    text = (proposal.extracted_at or proposal.date or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _append_note(existing: str | None, note: str) -> str:
    return f"{existing}; {note}" if existing else note


def confirm_and_expire_proposals(
    proposals: list[ProposalRow],
    log_rows,
    today: date,
    expire_days: int = DEFAULT_EXPIRE_DAYS,
) -> tuple[list[ProposalRow], list[ProposalRow]]:
    # Brian pasting a digest-provided row into Quick Entry IS the confirmation:
    # once the merge lands that row in the price log, the matching proposal
    # (same vendor/stem/date/per-stem price) flips to confirmed. Proposals
    # still unconfirmed after expire_days flip to expired. Mutates in place;
    # returns (confirmed, expired).
    # Match on (vendor, stem, date, per-stem price) — deliberately looser than
    # PriceLogRow.dedupe_key(), which also carries variety/grade: Brian's paste
    # may drop or reword variety text, and that must not block confirmation.
    log_keys = {
        (row.vendor_id, row.stem_id, row.date, round(row.price_per_stem, 4))
        for row in log_rows
    }
    confirmed: list[ProposalRow] = []
    expired: list[ProposalRow] = []
    for proposal in proposals:
        if proposal.status != "proposed":
            continue
        if proposal.price_per_stem is not None:
            key = (
                proposal.vendor_id, proposal.stem_id, proposal.date,
                round(proposal.price_per_stem, 4),
            )
            if key in log_keys:
                proposal.status = "confirmed"
                proposal.review_note = _append_note(
                    proposal.review_note, f"confirmed via Quick Entry match {today.isoformat()}",
                )
                confirmed.append(proposal)
                continue
        basis = _proposal_age_basis(proposal)
        if basis is not None and (today - basis).days > expire_days:
            proposal.status = "expired"
            proposal.review_note = _append_note(
                proposal.review_note,
                f"expired {today.isoformat()}: no confirmation within {expire_days} days",
            )
            expired.append(proposal)
    return confirmed, expired


def _reconcile_proposals(data_dir: Path, today: date, expire_days: int) -> tuple[int, int]:
    proposals_path = data_dir / "proposals.csv"
    proposals = read_proposals(proposals_path)
    log_rows = read_price_log(data_dir / "price-log.csv")
    confirmed, expired = confirm_and_expire_proposals(proposals, log_rows, today, expire_days)
    if confirmed or expired:
        write_proposals(proposals, proposals_path)
    return len(confirmed), len(expired)


# --- Subcommand implementations -------------------------------------------------

def _read_body(body_file: str | None) -> str:
    if body_file in (None, "-"):
        return sys.stdin.read()
    return Path(body_file).read_text(encoding="utf-8")


def _candidate_line(candidate) -> str:
    per_stem = f"${candidate.price_per_stem:.4f}/stem" if candidate.price_per_stem else "per-stem: ?"
    variety = f" '{candidate.variety}'" if candidate.variety else ""
    count = f" x{candidate.units_per_quote_unit:g}" if candidate.units_per_quote_unit else ""
    review = f"  REVIEW: {candidate.needs_review}" if candidate.needs_review else ""
    return (
        f"  [{candidate.confidence:6s}] {candidate.stem_id}{variety} ({candidate.grade}) "
        f"${candidate.quoted_price:g}/{candidate.quote_unit}{count} -> {per_stem}{review}"
    )


def cmd_parse_email(args: argparse.Namespace) -> int:
    body = _read_body(args.body_file)
    result = parse_quote_email(args.sender, args.subject, body, args.date)
    if result.vendor_id is None:
        print(f"sender {args.sender!r} does not match any vendor scope (vendors.json); nothing parsed")
        return 0
    print(f"vendor: {result.vendor_id} (matched {result.matched_term})")
    if not result.candidates:
        print("no quote candidates found in this email")
        return 0
    for candidate in result.candidates:
        print(_candidate_line(candidate))
    if not args.append:
        print(f"{len(result.candidates)} candidate(s); re-run with --append to write proposals")
        return 0

    data_dir = Path(args.data_dir)
    proposals_path = data_dir / "proposals.csv"
    existing = read_proposals(proposals_path)
    proposals = candidates_to_proposals(
        result, args.date,
        gmail_thread_id=args.thread_id, gmail_message_id=args.message_id,
        start_sequence=len(existing) + 1,
    )
    # Idempotent re-runs: skip rows already proposed from the same message
    # (or same-day identical values when no message id was given).
    def dedupe_key(row: ProposalRow) -> tuple:
        return (
            row.vendor_id, row.date, row.stem_id, row.quoted_price,
            row.quote_unit, row.gmail_message_id or "",
        )
    seen = {dedupe_key(row) for row in existing}
    appended = []
    for proposal in proposals:
        if dedupe_key(proposal) in seen:
            continue
        seen.add(dedupe_key(proposal))
        existing.append(proposal)
        appended.append(proposal)
    if appended:
        write_proposals(existing, proposals_path)
    print(f"appended {len(appended)} proposal(s) to {proposals_path} "
          f"({len(proposals) - len(appended)} duplicate(s) skipped)")
    return 0


def cmd_add_quote(args: argparse.Namespace) -> int:
    entry = {
        "date": args.date, "vendor_id": args.vendor, "stem_id": args.stem,
        "variety": args.variety or "", "grade": args.grade,
        "quoted_price": str(args.price), "quote_unit": args.unit,
        "units_per_quote_unit": "" if args.units is None else str(args.units),
        "currency": args.currency, "source": args.source,
        "baseline": "true" if args.baseline else "false",
        "valid_until": args.valid_until or "", "disruption_tag": args.disruption_tag or "",
        "notes": args.notes or "", "entered_by": args.entered_by,
    }
    assert list(entry) == QUICK_ENTRY_COLUMNS, "entry must mirror Quick Entry columns"
    data_dir = Path(args.data_dir)
    try:
        rows = quick_entry_entries_to_rows([entry], load_stems(CONFIG_DIR))
        added, skipped = merge_rows_into_price_log(rows, csv_path=data_dir / "price-log.csv")
    except ValidationError as error:
        print(f"rejected: {error}", file=sys.stderr)
        return 1
    for row in added:
        print(f"logged {row.id}: {row.vendor_id} / {row.stem_id} "
              f"${row.quoted_price:g}/{row.quote_unit} -> ${row.price_per_stem:.4f}/stem")
    for row in skipped:
        print(f"skipped duplicate: {row.vendor_id} / {row.stem_id} / {row.date} "
              f"(${row.price_per_stem:.4f}/stem already logged)")
    return 0


def cmd_merge_sheet(args: argparse.Namespace) -> int:
    # Thin wrapper over sheet_io: parse the downloaded Quick Entry surface
    # (xlsx workbook or Google Sheet CSV export), merge, then reconcile the
    # proposal loop against the updated log.
    workbook_path = Path(args.workbook)
    data_dir = Path(args.data_dir)
    today = date.fromisoformat(args.today)
    if workbook_path.suffix.lower() == ".csv":
        rows = parse_quick_entry_csv(workbook_path)
    else:
        rows = parse_quick_entry_tab(workbook_path)
    try:
        added, skipped = merge_rows_into_price_log(rows, csv_path=data_dir / "price-log.csv")
    except ValidationError as error:
        print(f"merge aborted: {error}", file=sys.stderr)
        return 1
    confirmed, expired = _reconcile_proposals(data_dir, today, args.expire_days)
    print(f"merged {len(added)} new row(s) into price-log.csv, {len(skipped)} duplicate(s) skipped; "
          f"proposals: {confirmed} confirmed, {expired} expired")
    return 0


def cmd_expire_proposals(args: argparse.Namespace) -> int:
    today = date.fromisoformat(args.today)
    confirmed, expired = _reconcile_proposals(Path(args.data_dir), today, args.expire_days)
    print(f"proposals: {confirmed} confirmed, {expired} expired "
          f"(threshold {args.expire_days} days)")
    return 0


def cmd_weekly_digest(args: argparse.Namespace) -> int:
    from .analysis import run_analysis
    from .digest import write_digest
    from .sheet_io import read_price_log, read_proposals

    today = date.fromisoformat(args.today)
    data_dir = Path(args.data_dir)
    log_rows = [row for row in read_price_log(data_dir / "price-log.csv")
                if row.status == "confirmed"]
    proposals = read_proposals(data_dir / "proposals.csv")
    result = run_analysis(log_rows, today)
    output = Path(args.output) if args.output else (
        PACKAGE_ROOT / "reports" / f"digest-{today.isoformat()}.md")
    write_digest(result, proposals, today, output)
    print(f"digest written to {output}")
    return 0


def cmd_export_accountant(args: argparse.Namespace) -> int:
    from .digest import write_accountant_export
    from .sheet_io import read_price_log

    data_dir = Path(args.data_dir)
    log_rows = read_price_log(data_dir / "price-log.csv")
    output = Path(args.output) if args.output else (
        PACKAGE_ROOT / "reports" / f"cogs-export-{args.year or 'all'}.csv")
    write_accountant_export(log_rows, output, year=args.year)
    print(f"accountant export written to {output}")
    return 0


# --- Parser wiring --------------------------------------------------------------

def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="directory holding price-log.csv / proposals.csv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pricemonitor",
        description="AFUVAI vendor price monitor — ingestion CLI (see agents/ingestion-agent.md)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    today = date.today().isoformat()

    parse_email = subparsers.add_parser(
        "parse-email", help="parse a vendor quote email body into proposal rows")
    parse_email.add_argument("--sender", required=True, help="From: address of the email")
    parse_email.add_argument("--date", default=today, help="received date, YYYY-MM-DD")
    parse_email.add_argument("--subject", default="", help="email subject line")
    parse_email.add_argument("--body-file", default=None,
                             help="path to a file with the email body text, or - for stdin (default)")
    parse_email.add_argument("--thread-id", default=None, help="Gmail thread id, for traceability")
    parse_email.add_argument("--message-id", default=None, help="Gmail message id, for traceability")
    parse_email.add_argument("--append", action="store_true",
                             help="append parsed candidates to data/proposals.csv as status=proposed")
    _add_common(parse_email)
    parse_email.set_defaults(func=cmd_parse_email)

    add_quote = subparsers.add_parser(
        "add-quote", help="manually log a confirmed quote straight into price-log.csv")
    add_quote.add_argument("--vendor", required=True, help="vendor_id from config/vendors.json")
    add_quote.add_argument("--stem", required=True, help="stem_id from config/stems.json")
    add_quote.add_argument("--price", required=True, type=float, help="quoted price in dollars")
    add_quote.add_argument("--unit", default="stem", choices=["stem", "bunch", "box"])
    add_quote.add_argument("--units", type=float, default=None,
                           help="stems per quote unit; omit on bunch quotes to use the stems.json default")
    add_quote.add_argument("--date", default=today, help="quote date, YYYY-MM-DD")
    add_quote.add_argument("--variety", default=None)
    add_quote.add_argument("--grade", default="standard", choices=["premium", "standard", "economy"])
    add_quote.add_argument("--currency", default="USD")
    add_quote.add_argument("--source", default="phone", choices=["email", "phone", "manual", "portal"])
    add_quote.add_argument("--baseline", action="store_true",
                           help="tag as the vendor's first (baseline) quote for this stem")
    add_quote.add_argument("--valid-until", default=None, help="YYYY-MM-DD the quote expires")
    add_quote.add_argument("--disruption-tag", default=None,
                           help="context for a spike, e.g. 'ecuador-export-disruption'")
    add_quote.add_argument("--notes", default=None)
    add_quote.add_argument("--entered-by", default="cli")
    _add_common(add_quote)
    add_quote.set_defaults(func=cmd_add_quote)

    merge_sheet = subparsers.add_parser(
        "merge-sheet", help="merge a downloaded Quick Entry workbook (.xlsx) or CSV into the price log")
    merge_sheet.add_argument("workbook", help="path to the downloaded workbook or Quick Entry CSV export")
    merge_sheet.add_argument("--expire-days", type=int, default=DEFAULT_EXPIRE_DAYS)
    merge_sheet.add_argument("--today", default=today, help=argparse.SUPPRESS)
    _add_common(merge_sheet)
    merge_sheet.set_defaults(func=cmd_merge_sheet)

    expire = subparsers.add_parser(
        "expire-proposals", help="confirm proposals matched in the price log; expire stale ones")
    expire.add_argument("--expire-days", type=int, default=DEFAULT_EXPIRE_DAYS)
    expire.add_argument("--today", default=today, help=argparse.SUPPRESS)
    _add_common(expire)
    expire.set_defaults(func=cmd_expire_proposals)

    weekly = subparsers.add_parser(
        "weekly-digest", help="run the analysis and write the weekly digest markdown")
    weekly.add_argument("--output", default=None,
                        help="output path (default reports/digest-<date>.md)")
    weekly.add_argument("--today", default=today, help=argparse.SUPPRESS)
    _add_common(weekly)
    weekly.set_defaults(func=cmd_weekly_digest)

    export = subparsers.add_parser(
        "export-accountant", help="COGS-ready CSV export matching Expense Tracker categories")
    export.add_argument("--year", type=int, default=None, help="restrict to one tax year")
    export.add_argument("--output", default=None,
                        help="output path (default reports/cogs-export-<year>.csv)")
    _add_common(export)
    export.set_defaults(func=cmd_export_accountant)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
