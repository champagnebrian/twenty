# WS5 tests: weekly digest rendering + accountant export.
# Run: python3 tests/test_digest.py

import csv
import sys
import tempfile
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pricemonitor.analysis import run_analysis
from pricemonitor.digest import (
    QUICK_ENTRY_PASTE_COLUMNS,
    render_digest,
    write_accountant_export,
)
from pricemonitor.models import PriceLogRow, ProposalRow


def _row(i, vendor, stem, price, quote_date, grade="standard", variety=None,
         quoted=None, unit="stem", per_unit=1):
    return PriceLogRow(
        id=f"t-{i}", date=quote_date, vendor_id=vendor, stem_id=stem,
        variety=variety, grade=grade, quoted_price=quoted or price,
        quote_unit=unit, units_per_quote_unit=per_unit, price_per_stem=price,
        source="manual", status="confirmed",
    )


def _fixture_rows(today: str = "2026-09-15") -> list[PriceLogRow]:
    # Two vendors quoting standard_rose (same grade) → comparison; a peony
    # history with a fresh off-season spike → flag; greenery so some tiers
    # can price partially.
    return [
        _row(1, "las-vegas-flower-market", "standard_rose", 0.75, "2026-09-01"),
        _row(2, "mayesh-las-vegas", "standard_rose", 0.95, "2026-09-03"),
        _row(3, "mayesh-las-vegas", "peony", 4.00, "2026-08-01"),
        _row(4, "mayesh-las-vegas", "peony", 4.10, "2026-08-20"),
        _row(5, "mayesh-las-vegas", "peony", 6.50, "2026-09-14"),
        _row(6, "las-vegas-flower-market", "eucalyptus", 1.10, "2026-09-05"),
        _row(7, "las-vegas-flower-market", "greenery_ruscus", 0.90, "2026-09-05"),
    ]


def test_digest_renders_all_sections_with_content():
    today = date(2026, 9, 15)
    rows = _fixture_rows()
    result = run_analysis(rows, today)
    proposals = [ProposalRow(
        id="em-1", date="2026-09-14", vendor_id="mayesh-las-vegas",
        stem_id="garden_rose", variety="Juliet", grade="premium",
        quoted_price=2.85, quote_unit="stem", units_per_quote_unit=1,
        price_per_stem=2.85, confidence=0.9, status="proposed",
    )]
    text = render_digest(result, proposals, today)
    for heading in ("# AFUVAI Vendor Price Monitor — Weekly Digest (2026-09-15)",
                    "## What moved", "## Tier margins", "## Cheapest vendor per stem",
                    "## Proposals awaiting your confirmation", "## Quote freshness",
                    "## Upcoming holiday order cutoffs"):
        assert heading in text, f"missing section: {heading}"
    # Comparison surfaces the cheaper vendor with its min-order constraint.
    assert "Las Vegas Flower Market at $0.75/stem" in text
    assert "min order $300.00" in text
    # Placeholder recipe caveat present while recipes are placeholders.
    assert "PLACEHOLDER" in text
    # Pending proposal renders a paste row with the right column count.
    paste_lines = [l for l in text.splitlines() if l.strip().startswith("`2026-09-14,")]
    assert paste_lines, "no paste row rendered for pending proposal"
    fields = paste_lines[0].strip().strip("`").split(",")
    assert len(fields) == len(QUICK_ENTRY_PASTE_COLUMNS), fields
    assert fields[1] == "mayesh-las-vegas" and fields[2] == "garden_rose"
    print("PASS  test_digest_renders_all_sections_with_content")


def test_digest_quiet_week_says_so():
    today = date(2026, 9, 15)
    rows = [_fixture_rows()[0]]
    result = run_analysis(rows, today)
    text = render_digest(result, [], today)
    assert "Needs attention:" in text
    assert "quiet week" in text or "0 " not in text.splitlines()[2]
    print("PASS  test_digest_quiet_week_says_so")


def test_accountant_export_matches_categories_and_filters():
    rows = _fixture_rows() + [PriceLogRow(
        id="s-1", date="2025-12-30", vendor_id="mayesh-las-vegas",
        stem_id="peony", variety=None, grade="standard", quoted_price=3.0,
        quote_unit="stem", units_per_quote_unit=1, price_per_stem=3.0,
        source="manual", status="sample",
    )]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cogs.csv"
        write_accountant_export(rows, out, year=2026)
        with open(out, newline="", encoding="utf-8") as handle:
            exported = list(csv.DictReader(handle))
    # sample row and non-2026 rows excluded; all rows carry the Expense
    # Tracker category verbatim.
    assert len(exported) == len(_fixture_rows())
    assert all(r["category"] == "Floral Inventory & Supplies" for r in exported)
    assert all(r["date"].startswith("2026") for r in exported)
    peony_rows = [r for r in exported if "peony" in r["description"]]
    assert peony_rows and peony_rows[0]["unit_price_per_stem"] in ("4.0000", "4.1000", "6.5000")
    print("PASS  test_accountant_export_matches_categories_and_filters")


if __name__ == "__main__":
    test_digest_renders_all_sections_with_content()
    test_digest_quiet_week_says_so()
    test_accountant_export_matches_categories_and_filters()
    print("\nOK: all digest tests passed")
