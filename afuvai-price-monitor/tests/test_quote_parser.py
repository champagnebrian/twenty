# WS3 tests: vendor scoping (incl. the LVFM full-address-not-gmail.com rule
# and alias_of), realistic vendor-reply fixtures, normalization math,
# confidence grading, the invoice-yields-nothing rule, and the full
# proposal → Quick Entry confirmation / expiry loop through the CLI.
# Run with `python3 tests/test_quote_parser.py` or `python3 -m pytest tests/`.

import csv
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pricemonitor.cli import confirm_and_expire_proposals, main as cli_main
from pricemonitor.models import load_stems, load_vendors
from pricemonitor.quote_parser import (
    CONFIDENCE_SCORES,
    build_gmail_queries,
    candidates_to_proposals,
    parse_quote_email,
    resolve_vendor,
)
from pricemonitor.sheet_io import QUICK_ENTRY_COLUMNS, read_price_log, read_proposals

RECEIVED = "2026-07-17"

# Synthetic registry for scoping rules the real config cannot exercise
# (alias with its own domain, a misconfigured freemail domain entry,
# an emailless vendor).
SYNTHETIC_VENDORS = {
    "vendors": [
        {"id": "acme", "name": "Acme Flowers",
         "contact": {"email": "sales@acme-flowers.com"},
         "email_domains": ["acme-flowers.com"]},
        {"id": "acme-branch", "alias_of": "acme", "name": "Acme Branch",
         "contact": {"email": "branch@acme-branch.com"},
         "email_domains": ["acme-branch.com"]},
        {"id": "freemail-vendor", "name": "Freemail Vendor",
         "contact": {"email": "freemailvendor@gmail.com"},
         "email_domains": ["gmail.com"]},
        {"id": "no-domains", "name": "Phone Only Vendor",
         "contact": {"email": "owner@phone-only.com"},
         "email_domains": []},
    ]
}

# --- Fixtures: 5 realistic vendor-reply bodies ----------------------------------

MAYESH_AVAILABILITY = """\
Good morning Brian,

Here's this week's availability on the stems you asked about:

- Standard Roses (Freedom Red) - $1.85 per stem, premium grade
- Garden Roses - $2.40/stem
- Peonies (Sarah Bernhardt) - bunch of 10 at $42.50
- Eucalyptus (Silver Dollar) - $9.50 a bunch

Prices valid through July 24. Let me know counts and I'll get it on the truck.

Mayesh Las Vegas
"""

LVFM_ORDER_CONFIRMATION = """\
Hi Brian,

Thanks for reaching out! Here is your quote:

50 stems Freedom Red Roses at $0.95 per stem
Hydrangea $22.50 per bunch of 5

Quote valid until 07/24/2026. Pickup or delivery Mon-Sat 10am-3pm ($18.95 delivery fee, $300 minimum for wholesale).

Las Vegas Flower Market
"""

TERSE_PHONE_FOLLOWUP = """\
Brian - following up from the call.

dahlias $3.25
peonies 5.50/stem while they last

- Gene
"""

MULTI_STEM_MIXED_UNITS = """\
Hi Brian, prices below:

Spray roses: bunches of 10 at $8.90
Ranunculus: $55 per box of 100
Stock $6.50/bu
Lisianthus $4.00 a bunch, utility grade

Terms: net 30 once your account clears.
"""

INVOICE_REMINDER = """\
Hi Brian,

Friendly reminder that invoice #10382 for $482.50 is past due.
Please remit payment at your earliest convenience. Net 30 terms.
Your current account balance is $482.50.

Mayesh Accounting
"""

MESSY_QUOTE = """\
Hey Brian,

Peonies are running high this week, everything out of Alaska.
$60 for the bunch if you still want them.

Talk soon
"""


def _by_stem(result):
    return {candidate.stem_id: candidate for candidate in result.candidates}


# --- Vendor resolution ----------------------------------------------------------

def test_vendor_resolution_scope_rules():
    vendors = load_vendors()

    # Domain match against a real vendor domain.
    assert resolve_vendor("availability@mayesh.com", vendors)[0] == "mayesh-las-vegas"
    assert resolve_vendor("Sales Rep <someone@lvfloral.com>", vendors)[0] == "lv-floral-wholesale"

    # LVFM rule: their contact is a gmail.com address — full-address match
    # works, but any OTHER gmail.com sender must never match.
    assert resolve_vendor(
        "Las Vegas Flower Market <lasvegasflowermarket@gmail.com>", vendors
    )[0] == "las-vegas-flower-market"
    assert resolve_vendor("randomflorist@gmail.com", vendors) is None

    # Unknown sender → None.
    assert resolve_vendor("spam@flowerdeals.biz", vendors) is None

    # Synthetic rules: alias resolves to target; a freemail domain entry is
    # never matched as a domain (full contact address still works); a vendor
    # with empty email_domains is skipped even though it has a contact email.
    assert resolve_vendor("orders@acme-branch.com", SYNTHETIC_VENDORS)[0] == "acme"
    assert resolve_vendor("anyone-at-all@gmail.com", SYNTHETIC_VENDORS) is None
    assert resolve_vendor("freemailvendor@gmail.com", SYNTHETIC_VENDORS)[0] == "freemail-vendor"
    assert resolve_vendor("owner@phone-only.com", SYNTHETIC_VENDORS) is None


def test_gmail_queries_built_only_from_vendor_scope():
    queries = build_gmail_queries(after="2026/07/01")
    # Only active vendors with a Gmail footprint get a query; aliases,
    # inactive branches, and emailless branches are absent.
    assert set(queries) == {
        "lv-floral-wholesale", "fss-las-vegas", "greenleaf-sparks",
        "sdfs-las-vegas", "las-vegas-flower-market", "mayesh-las-vegas",
    }
    for query in queries.values():
        assert query.startswith("from:")
        assert query.endswith("after:2026/07/01")
        # gmail.com may appear ONLY inside LVFM's full address, never bare.
        assert query.count("gmail.com") == query.count("lasvegasflowermarket@gmail.com")
    assert "lasvegasflowermarket@gmail.com" in queries["las-vegas-flower-market"]
    assert "lasvegasflowermarket.com" in queries["las-vegas-flower-market"]


# --- Fixture parsing ------------------------------------------------------------

def test_mayesh_availability_list():
    result = parse_quote_email(
        "availability@mayesh.com", "This week's availability", MAYESH_AVAILABILITY, RECEIVED)
    assert result.vendor_id == "mayesh-las-vegas"
    assert len(result.candidates) == 4
    by_stem = _by_stem(result)

    rose = by_stem["standard_rose"]
    assert rose.variety == "Freedom Red"
    assert rose.grade == "premium"
    assert rose.quote_unit == "stem" and rose.price_per_stem == 1.85
    assert rose.confidence == "high" and rose.needs_review is None

    garden = by_stem["garden_rose"]
    assert garden.price_per_stem == 2.4 and garden.confidence == "high"
    assert garden.grade == "standard"  # no grade word → default

    peony = by_stem["peony"]
    assert peony.variety == "Sarah Bernhardt"
    assert peony.quote_unit == "bunch" and peony.units_per_quote_unit == 10
    assert peony.price_per_stem == 4.25  # 42.50 / explicit 10
    assert peony.confidence == "high"

    euc = by_stem["eucalyptus"]
    assert euc.units_per_quote_unit == 10  # stems.json bunch default
    assert euc.price_per_stem == 0.95
    assert euc.confidence == "medium"  # defaulted count → not high
    assert any("defaulted" in note for note in euc.info_notes)

    # Stated validity is captured on every candidate.
    assert all(candidate.valid_until == "2026-07-24" for candidate in result.candidates)


def test_lvfm_order_confirmation_full_address_and_validity():
    result = parse_quote_email(
        "Las Vegas Flower Market <lasvegasflowermarket@gmail.com>",
        "Quote for your order", LVFM_ORDER_CONFIRMATION, RECEIVED)
    assert result.vendor_id == "las-vegas-flower-market"
    by_stem = _by_stem(result)
    assert set(by_stem) == {"standard_rose", "hydrangea"}

    rose = by_stem["standard_rose"]
    assert rose.variety == "Freedom Red"
    assert rose.price_per_stem == 0.95 and rose.confidence == "high"

    hydrangea = by_stem["hydrangea"]
    assert hydrangea.quote_unit == "bunch" and hydrangea.units_per_quote_unit == 5
    assert hydrangea.price_per_stem == 4.5  # 22.50 / explicit 5, not default
    assert hydrangea.confidence == "high"

    # MM/DD/YYYY validity; the fee/minimum line produced no candidates.
    assert rose.valid_until == "2026-07-24"

    # The same body from an unknown gmail sender parses to nothing at all.
    stranger = parse_quote_email(
        "otherflorist@gmail.com", "Quote", LVFM_ORDER_CONFIRMATION, RECEIVED)
    assert stranger.vendor_id is None and stranger.candidates == []


def test_terse_phone_followup_confidence_grading():
    result = parse_quote_email(
        "genew@sdfsinc.com", "Re: quote request", TERSE_PHONE_FOLLOWUP, RECEIVED)
    assert result.vendor_id == "sdfs-las-vegas"
    by_stem = _by_stem(result)

    dahlia = by_stem["dahlia"]  # "dahlias $3.25" — no unit anywhere
    assert dahlia.confidence == "low"
    assert dahlia.quote_unit == "stem" and dahlia.price_per_stem == 3.25
    assert "assumed per stem" in dahlia.needs_review

    peony = by_stem["peony"]  # "5.50/stem" — explicit even without a $
    assert peony.confidence == "high"
    assert peony.price_per_stem == 5.5 and peony.needs_review is None


def test_multi_stem_mixed_units_normalization():
    result = parse_quote_email(
        "orders@lvfloral.com", "Pricing for AFUVAI", MULTI_STEM_MIXED_UNITS, RECEIVED)
    assert result.vendor_id == "lv-floral-wholesale"
    by_stem = _by_stem(result)
    assert set(by_stem) == {"spray_rose", "ranunculus", "stock", "lisianthus"}

    spray = by_stem["spray_rose"]  # count-first pattern: bunches of 10 at $8.90
    assert (spray.quote_unit, spray.units_per_quote_unit, spray.price_per_stem) == ("bunch", 10, 0.89)
    assert spray.confidence == "high"

    ranunculus = by_stem["ranunculus"]  # $55 per box of 100
    assert (ranunculus.quote_unit, ranunculus.units_per_quote_unit) == ("box", 100)
    assert ranunculus.price_per_stem == 0.55 and ranunculus.confidence == "high"

    stock = by_stem["stock"]  # $6.50/bu → bunch default 10
    assert stock.quote_unit == "bunch" and stock.units_per_quote_unit == 10
    assert stock.price_per_stem == 0.65 and stock.confidence == "medium"

    lisianthus = by_stem["lisianthus"]  # utility grade → economy
    assert lisianthus.grade == "economy"
    assert lisianthus.price_per_stem == 0.4

    assert all(candidate.valid_until is None for candidate in result.candidates)


def test_invoice_reminder_yields_zero_proposals():
    result = parse_quote_email(
        "accounting@mayesh.com", "Invoice #10382 past due", INVOICE_REMINDER, RECEIVED)
    assert result.vendor_id == "mayesh-las-vegas"  # in scope, but not a quote
    assert result.candidates == []
    assert candidates_to_proposals(result, RECEIVED) == []


def test_messy_quote_becomes_low_confidence_proposal_not_a_drop():
    result = parse_quote_email(
        "lasvegasflowermarket@gmail.com", "peonies", MESSY_QUOTE, RECEIVED)
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.stem_id == "peony"
    assert candidate.confidence == "low"
    assert candidate.needs_review is not None  # flagged for Brian, not guessed
    assert candidate.quoted_price == 60.0


# --- Proposal conversion and the confirmation loop ------------------------------

def test_candidates_to_proposals_rows():
    result = parse_quote_email(
        "availability@mayesh.com", "Availability", MAYESH_AVAILABILITY, RECEIVED)
    proposals = candidates_to_proposals(
        result, RECEIVED, gmail_thread_id="t-1", gmail_message_id="m-1",
        start_sequence=3, extracted_at="2026-07-17T09:00:00+00:00")
    assert len(proposals) == 4
    assert [proposal.id for proposal in proposals][:2] == ["em-20260717-0003", "em-20260717-0004"]
    for proposal in proposals:
        proposal.validate()
        assert proposal.status == "proposed"
        assert proposal.source == "email"
        assert proposal.vendor_id == "mayesh-las-vegas"
        assert proposal.gmail_thread_id == "t-1"
        assert proposal.confidence in CONFIDENCE_SCORES.values()
        assert proposal.notes and "parsed from" in proposal.notes


def _make_data_dir() -> Path:
    workdir = Path(tempfile.mkdtemp(prefix="afuvai-quote-parser-"))
    data_dir = workdir / "data"
    data_dir.mkdir()
    for name in ("price-log.csv", "proposals.csv", "tier-price-history.csv"):
        shutil.copy(PROJECT_ROOT / "data" / name, data_dir / name)
    return data_dir


def test_cli_parse_email_append_is_idempotent():
    data_dir = _make_data_dir()
    body_file = data_dir / "email.txt"
    body_file.write_text(LVFM_ORDER_CONFIRMATION, encoding="utf-8")
    argv = [
        "parse-email", "--sender", "lasvegasflowermarket@gmail.com",
        "--date", RECEIVED, "--subject", "Quote for your order",
        "--body-file", str(body_file), "--message-id", "m-777",
        "--append", "--data-dir", str(data_dir),
    ]
    assert cli_main(argv) == 0
    proposals = read_proposals(data_dir / "proposals.csv")
    assert len(proposals) == 2
    assert all(proposal.status == "proposed" for proposal in proposals)
    # Second run with the same message appends nothing.
    assert cli_main(argv) == 0
    assert len(read_proposals(data_dir / "proposals.csv")) == 2


def test_confirmation_loop_quick_entry_paste_confirms_and_stale_expires():
    # The full WS3 loop: proposals land as proposed → Brian pastes the digest's
    # pre-formatted Quick Entry row for the one he accepts → merge-sheet flips
    # that proposal to confirmed; a 30-day-old proposal expires.
    data_dir = _make_data_dir()
    body_file = data_dir / "email.txt"
    body_file.write_text(LVFM_ORDER_CONFIRMATION, encoding="utf-8")
    cli_main([
        "parse-email", "--sender", "lasvegasflowermarket@gmail.com",
        "--date", RECEIVED, "--body-file", str(body_file),
        "--message-id", "m-1", "--append", "--data-dir", str(data_dir),
    ])
    # Age one proposal past the 21-day window (simulates an old, ignored one).
    proposals = read_proposals(data_dir / "proposals.csv")
    hydrangea = next(p for p in proposals if p.stem_id == "hydrangea")
    rose = next(p for p in proposals if p.stem_id == "standard_rose")
    rose.date, rose.extracted_at = "2026-06-10", "2026-06-10T09:00:00+00:00"
    from pricemonitor.sheet_io import write_proposals
    write_proposals(proposals, data_dir / "proposals.csv")

    # Brian's paste: the hydrangea row, exactly as the digest pre-formats it
    # (same date/vendor/stem/price/unit → same dedupe key after merge).
    quick_entry_csv = data_dir / "quick-entry-download.csv"
    with open(quick_entry_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["AFUVAI Vendor Price Monitor — Quick Entry (legend line)"])
        writer.writerow(QUICK_ENTRY_COLUMNS)
        writer.writerow([
            RECEIVED, "las-vegas-flower-market", "hydrangea", "", "standard",
            "22.50", "bunch", "5", "USD", "email", "true", "2026-07-24", "",
            "accepting proposal em-20260717-0002", "brian",
        ])
    assert cli_main([
        "merge-sheet", str(quick_entry_csv), "--data-dir", str(data_dir),
        "--today", RECEIVED,
    ]) == 0

    log_rows = read_price_log(data_dir / "price-log.csv")
    merged = next(row for row in log_rows if row.stem_id == "hydrangea")
    assert merged.price_per_stem == 4.5 and merged.status == "confirmed"

    proposals = {p.stem_id: p for p in read_proposals(data_dir / "proposals.csv")}
    assert proposals["hydrangea"].status == "confirmed"
    assert "Quick Entry match" in proposals["hydrangea"].review_note
    assert proposals["standard_rose"].status == "expired"
    assert "no confirmation within 21 days" in proposals["standard_rose"].review_note

    # Re-running the merge is a no-op (idempotent weekly job).
    assert cli_main([
        "merge-sheet", str(quick_entry_csv), "--data-dir", str(data_dir),
        "--today", RECEIVED,
    ]) == 0
    assert len(read_price_log(data_dir / "price-log.csv")) == len(log_rows)


def test_confirm_helper_ignores_unnormalizable_proposals():
    # A low-confidence proposal without a per-stem price can never auto-match;
    # it just ages out.
    from pricemonitor.models import ProposalRow
    proposal = ProposalRow(
        id="em-1", date="2026-06-01", vendor_id="mayesh-las-vegas",
        stem_id="peony", variety=None, grade="standard", quoted_price=60.0,
        quote_unit="box", units_per_quote_unit=None, price_per_stem=None,
        extracted_at="2026-06-01T00:00:00+00:00", confidence=0.3, status="proposed",
    )
    confirmed, expired = confirm_and_expire_proposals([proposal], [], date(2026, 7, 17))
    assert confirmed == [] and expired == [proposal]
    assert proposal.status == "expired"


if __name__ == "__main__":
    test_vendor_resolution_scope_rules()
    test_gmail_queries_built_only_from_vendor_scope()
    test_mayesh_availability_list()
    test_lvfm_order_confirmation_full_address_and_validity()
    test_terse_phone_followup_confidence_grading()
    test_multi_stem_mixed_units_normalization()
    test_invoice_reminder_yields_zero_proposals()
    test_messy_quote_becomes_low_confidence_proposal_not_a_drop()
    test_candidates_to_proposals_rows()
    test_cli_parse_email_append_is_idempotent()
    test_confirmation_loop_quick_entry_paste_confirms_and_stale_expires()
    test_confirm_helper_ignores_unnormalizable_proposals()
    print("OK: all quote parser + ingestion loop tests passed")
