# Scenario tests for WS4 (margin / threshold / seasonality logic).
# Run with `python3 tests/test_analysis.py` (or pytest). Fixture price-log rows
# are built in-test (status=confirmed); real config/ JSON is used except for
# tier recipes, which each scenario injects with known retail prices (the
# shipped tier-recipes.json has placeholder recipes with null retail).

import copy
import csv
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pricemonitor.models import (
    PriceLogRow,
    load_seasonal_calendar,
    load_stems,
    load_thresholds,
    load_vendors,
)
from pricemonitor.analysis import run_analysis
from pricemonitor.detection import (
    SEVERITY_ALERT,
    SEVERITY_WATCH,
    CLASSIFICATION_EXPECTED_SEASONAL,
    CLASSIFICATION_MARKET_BAND_MOVE,
)
from pricemonitor.margin import TIER_STATUS_INCOMPUTABLE, snapshot_tier_pricing
from pricemonitor.seasonality import resolve_seasonal_context

VENDORS = load_vendors()
STEMS = load_stems()
CALENDAR = load_seasonal_calendar()
THRESHOLDS = load_thresholds()

_row_counter = 0


def make_row(vendor_id, stem_id, day, price, grade="standard", disruption_tag=None):
    global _row_counter
    _row_counter += 1
    return PriceLogRow(
        id=f"test-{_row_counter:04d}", date=day, vendor_id=vendor_id, stem_id=stem_id,
        variety=None, grade=grade, quoted_price=price, quote_unit="stem",
        units_per_quote_unit=1, price_per_stem=price, source="manual",
        disruption_tag=disruption_tag, entered_by="test", status="confirmed",
    )


def make_tier(tier_id, recipe, retail, placeholder=True):
    return {
        "tier_id": tier_id, "name": tier_id, "retail_price_usd": retail,
        "margin_target": 0.6, "recipe": recipe, "placeholder": placeholder, "notes": None,
    }


def tiers_cfg(*tiers):
    return {"tiers": list(tiers)}


def analyze(rows, today, tiers):
    return run_analysis(
        rows, today, vendors_config=VENDORS, stems_config=STEMS,
        tiers_config=tiers, calendar=CALENDAR, thresholds=THRESHOLDS,
    )


def flagged(result):
    return [m for m in result.moves if m.severity in (SEVERITY_WATCH, SEVERITY_ALERT)]


# (a) 10% move on cheap greenery: dollar impact ~$1 < $25 minimum, margins hold
# -> no WATCH/ALERT.
def test_a_cheap_greenery_move_not_flagged():
    tiers = tiers_cfg(make_tier(
        "greenery-tier", [{"stem_id": "greenery_ruscus", "count": 20, "grade": "standard"}], 40.0,
    ))
    rows = [
        make_row("mayesh-las-vegas", "greenery_ruscus", "2026-11-01", 0.50),
        make_row("mayesh-las-vegas", "greenery_ruscus", "2026-11-15", 0.55),  # +10%
    ]
    result = analyze(rows, date(2026, 11, 20), tiers)
    assert flagged(result) == [], [(m.stem_id, m.severity, m.reasons) for m in flagged(result)]
    tier = result.tier_margins[0]
    assert tier.status == "ok", tier
    assert abs(tier.cogs_usd - 11.0) < 1e-6, tier.cogs_usd


# (b) 5% peony move during wedding season pushes a tier below the 0.55 floor
# -> ALERT with the tier named, even though dollar impact ($2) is tiny.
def test_b_peony_move_breaches_alert_floor_during_wedding_season():
    tiers = tiers_cfg(make_tier(
        "test-peony-tier", [{"stem_id": "peony", "count": 10, "grade": "standard"}], 93.0,
    ))
    rows = [
        make_row("mayesh-las-vegas", "peony", "2026-05-20", 4.00),
        make_row("mayesh-las-vegas", "peony", "2026-06-01", 4.00),
        make_row("mayesh-las-vegas", "peony", "2026-06-10", 4.20),  # +5%
    ]
    result = analyze(rows, date(2026, 6, 15), tiers)
    moves = [m for m in result.moves if m.stem_id == "peony"]
    assert len(moves) == 1, result.moves
    move = moves[0]
    assert move.severity == SEVERITY_ALERT, (move.severity, move.reasons)
    assert any("test-peony-tier" in reason for reason in move.reasons), move.reasons
    tier = result.tier_margins[0]
    assert tier.status == "alert", tier
    assert tier.margin < 0.55, tier.margin
    # Wedding-season multiplier for peony is 1.0 (in season) — the move is a
    # genuine deviation, not an expected seasonal lift.
    assert move.seasonal_multiplier == 1.0, move.seasonal_multiplier
    # Placeholder flag carries through so the digest can caveat dollar figures.
    assert result.placeholder_recipes is True
    assert tier.placeholder is True


# (c) Rose price doubles inside the Valentine's window (x2.0 expected) with
# margins holding -> expected-seasonal INFO, not an alert.
def test_c_valentines_rose_doubling_is_expected_seasonal():
    tiers = tiers_cfg(make_tier(
        "test-rose-tier", [{"stem_id": "standard_rose", "count": 25, "grade": "standard"}], 100.0,
    ))
    rows = [
        make_row("mayesh-las-vegas", "standard_rose", "2025-12-20", 0.75),
        make_row("mayesh-las-vegas", "standard_rose", "2026-01-05", 0.75),
        make_row("mayesh-las-vegas", "standard_rose", "2026-02-01", 1.50),  # x2 in window
    ]
    result = analyze(rows, date(2026, 2, 5), tiers)
    assert flagged(result) == [], [(m.severity, m.reasons) for m in flagged(result)]
    moves = [m for m in result.moves if m.stem_id == "standard_rose"]
    assert len(moves) == 1, result.moves
    move = moves[0]
    assert move.classification == CLASSIFICATION_EXPECTED_SEASONAL, move
    assert move.severity == "INFO", move.severity
    assert move.seasonal_multiplier == 2.0, move.seasonal_multiplier
    assert "valentines" in move.window_ids, move.window_ids
    assert result.tier_margins[0].status == "ok", result.tier_margins[0]


# (d) The same rose doubling in September (no Valentine's multiplier) -> flagged.
def test_d_september_rose_doubling_is_flagged():
    tiers = tiers_cfg(make_tier(
        "test-rose-tier", [{"stem_id": "standard_rose", "count": 50, "grade": "standard"}], 100.0,
    ))
    rows = [
        make_row("mayesh-las-vegas", "standard_rose", "2026-07-01", 0.75),
        make_row("mayesh-las-vegas", "standard_rose", "2026-08-01", 0.75),
        make_row("mayesh-las-vegas", "standard_rose", "2026-09-10", 1.50),  # x2 off-holiday
    ]
    result = analyze(rows, date(2026, 9, 15), tiers)
    moves = [m for m in result.moves if m.stem_id == "standard_rose"]
    assert len(moves) == 1, result.moves
    move = moves[0]
    assert move.severity in (SEVERITY_WATCH, SEVERITY_ALERT), (move.severity, move.reasons)
    assert move.classification != CLASSIFICATION_EXPECTED_SEASONAL, move.classification
    # Wedding season's generic x1.15 applies, but a doubling still deviates hard.
    assert move.seasonal_deviation_pct > 0.5, move.seasonal_deviation_pct
    impacts = {i.tier_id: i.dollar_impact_usd for i in move.tier_impacts}
    assert impacts["test-rose-tier"] >= THRESHOLDS["min_tier_dollar_impact_usd"], impacts


# (e) Stale quote (>90d) excluded from comparison/best-price and listed in
# reminders; aging quote (60-90d) still counts as current but gets a reminder.
def test_e_stale_quote_excluded_and_reminded():
    tiers = tiers_cfg()
    rows = [
        make_row("lv-floral-wholesale", "standard_rose", "2026-03-01", 0.70),  # 138d stale
        make_row("mayesh-las-vegas", "standard_rose", "2026-07-01", 0.80),     # fresh
        make_row("sdfs-las-vegas", "standard_rose", "2026-05-10", 0.85),       # 68d aging
    ]
    result = analyze(rows, date(2026, 7, 17), tiers)
    # Stale vendor is out of best-price and comparison entirely.
    best = {(p.stem_id, p.grade): p for p in result.best_prices}
    assert best[("standard_rose", "standard")].vendor_id == "mayesh-las-vegas", best
    assert len(result.comparisons) == 1, result.comparisons
    comparison = result.comparisons[0]
    vendor_ids = {q.vendor_id for q in comparison.quotes}
    assert "lv-floral-wholesale" not in vendor_ids, vendor_ids
    assert vendor_ids == {"mayesh-las-vegas", "sdfs-las-vegas"}, vendor_ids
    assert comparison.cheapest.vendor_id == "mayesh-las-vegas"
    # Reminders.
    assert [(r.vendor_id, r.freshness) for r in result.stale_quotes] == [
        ("lv-floral-wholesale", "stale")
    ], result.stale_quotes
    assert [(r.vendor_id, r.freshness) for r in result.aging_quotes] == [
        ("sdfs-las-vegas", "aging")
    ], result.aging_quotes


# (f) Different grades are never compared; same grade -> cheapest surfaced with
# min-order annotation from vendors.json.
def test_f_grade_isolation_and_min_order_annotation():
    tiers = tiers_cfg()
    today = date(2026, 7, 17)
    different_grades = [
        make_row("las-vegas-flower-market", "standard_rose", "2026-07-01", 0.70, grade="standard"),
        make_row("mayesh-las-vegas", "standard_rose", "2026-07-05", 0.90, grade="premium"),
    ]
    result = analyze(different_grades, today, tiers)
    assert result.comparisons == [], result.comparisons  # 1 vendor per grade

    same_grade = different_grades + [
        make_row("sdfs-las-vegas", "standard_rose", "2026-07-03", 0.80, grade="standard"),
    ]
    result = analyze(same_grade, today, tiers)
    assert len(result.comparisons) == 1, result.comparisons
    comparison = result.comparisons[0]
    assert comparison.grade == "standard"
    assert all(q.grade == "standard" for q in comparison.quotes), comparison.quotes
    assert comparison.cheapest.vendor_id == "las-vegas-flower-market", comparison.cheapest
    # min_order_usd 300 comes straight from vendors.json for LV Flower Market.
    assert comparison.cheapest.min_order_usd == 300, comparison.cheapest
    assert comparison.spread_pct > 0, comparison.spread_pct


# (g) Market-price stem band move >= 15% -> custom-quote reprice flag + the
# substitution map (with current best prices where quoted) + disruption tag.
def test_g_market_band_move_triggers_reprice_and_substitutions():
    tiers = tiers_cfg()  # dahlia is custom-quote, not in any tier
    rows = [
        make_row("las-vegas-flower-market", "dahlia", "2026-08-01", 3.00),
        make_row("las-vegas-flower-market", "dahlia", "2026-08-20", 3.00),
        make_row(
            "las-vegas-flower-market", "dahlia", "2026-09-10", 3.60,  # +20% >= 15% band
            disruption_tag="ecuador export disruption",
        ),
        make_row("mayesh-las-vegas", "garden_rose", "2026-09-01", 2.50, grade="premium"),
    ]
    result = analyze(rows, date(2026, 9, 15), tiers)
    moves = [m for m in result.moves if m.stem_id == "dahlia"]
    assert len(moves) == 1, result.moves
    move = moves[0]
    assert move.severity == SEVERITY_ALERT, (move.severity, move.reasons)
    assert move.classification == CLASSIFICATION_MARKET_BAND_MOVE, move.classification
    assert move.custom_quote_reprice is True
    assert move.disruption_tag == "ecuador export disruption"
    subs = {s.stem_id: s for s in move.substitutions}
    assert "garden_rose" in subs, subs
    assert subs["garden_rose"].quoted is True
    assert subs["garden_rose"].best_price_per_stem == 2.50, subs["garden_rose"]
    assert subs["garden_rose"].vendor_id == "mayesh-las-vegas"
    # Not-yet-tracked substitutes surface as unquoted, never invented prices.
    unquoted = [s for s in move.substitutions if not s.quoted]
    assert unquoted and all(s.best_price_per_stem is None for s in unquoted), move.substitutions


# (h) A tier with a stem nobody has quoted -> incomputable with the missing
# list, never silently zero. Also: grade fallback happens with a note.
def test_h_incomputable_tier_and_grade_fallback():
    tiers = tiers_cfg(
        make_tier("test-missing", [
            {"stem_id": "standard_rose", "count": 10, "grade": "standard"},
            {"stem_id": "peony", "count": 5, "grade": "standard"},
        ], 80.0),
        make_tier("fallback-tier", [
            {"stem_id": "standard_rose", "count": 10, "grade": "premium"},
        ], 50.0),
    )
    rows = [make_row("mayesh-las-vegas", "standard_rose", "2026-07-01", 0.80)]
    result = analyze(rows, date(2026, 7, 17), tiers)
    by_id = {t.tier_id: t for t in result.tier_margins}

    missing_tier = by_id["test-missing"]
    assert missing_tier.status == TIER_STATUS_INCOMPUTABLE, missing_tier
    assert missing_tier.missing_stems == ["peony"], missing_tier.missing_stems
    assert missing_tier.cogs_usd is None and missing_tier.margin is None, missing_tier

    fallback_tier = by_id["fallback-tier"]
    assert fallback_tier.status == "ok", fallback_tier
    assert fallback_tier.stem_costs[0].grade == "standard"  # fell back from premium
    assert fallback_tier.stem_costs[0].grade_fallback_note is not None, fallback_tier.stem_costs


# (i) snapshot_tier_pricing appends to tier-price-history.csv — append-only,
# one header, prior content untouched.
def test_i_snapshot_appends_to_tier_price_history():
    tiers = tiers_cfg(make_tier(
        "snap-tier", [{"stem_id": "standard_rose", "count": 10, "grade": "standard"}], 50.0,
    ))
    rows = [make_row("mayesh-las-vegas", "standard_rose", "2026-07-01", 0.80)]
    result = analyze(rows, date(2026, 7, 17), tiers)
    history_path = Path(tempfile.mkdtemp(prefix="afuvai-analysis-")) / "tier-price-history.csv"

    snapshot_tier_pricing(
        result.tier_margins, trigger="alert:test", note="scenario i",
        csv_path=history_path, snapshot_date="2026-07-17",
    )
    first_content = history_path.read_text(encoding="utf-8")
    snapshot_tier_pricing(
        result.tier_margins, trigger="alert:test-2",
        csv_path=history_path, snapshot_date="2026-07-24",
    )
    second_content = history_path.read_text(encoding="utf-8")
    assert second_content.startswith(first_content), "history was rewritten, not appended"
    with open(history_path, newline="", encoding="utf-8") as handle:
        parsed = list(csv.DictReader(handle))
    assert len(parsed) == 2, parsed
    assert [p["trigger"] for p in parsed] == ["alert:test", "alert:test-2"], parsed
    assert parsed[0]["computed_cogs_usd"] == "8", parsed[0]
    assert second_content.count("snapshot_date") == 1  # single header


# (j) Seasonal window resolution edges + upcoming holiday cutoff surfacing.
def test_j_seasonality_windows_and_holiday_cutoffs():
    # Inclusive bounds: Feb 14 is in the Valentine's window, Feb 15 is not.
    assert resolve_seasonal_context("standard_rose", date(2026, 2, 14), CALENDAR).multiplier == 2.0
    assert resolve_seasonal_context("standard_rose", date(2026, 2, 15), CALENDAR).multiplier == 1.0
    # Peony inside wedding season keeps multiplier 1.0 (in-season override).
    assert resolve_seasonal_context("peony", date(2026, 6, 15), CALENDAR).multiplier == 1.0
    # Rose in overlapping Mother's Day + wedding season windows: max wins (1.5).
    context = resolve_seasonal_context("standard_rose", date(2026, 5, 10), CALENDAR)
    assert context.multiplier == 1.5 and context.driving_window_id == "mothers_day", context

    # Holiday lookup 25 days out: valentines surfaces with a known vendor cutoff.
    vendors = copy.deepcopy(VENDORS)
    for vendor in vendors["vendors"]:
        if vendor["id"] == "mayesh-las-vegas":
            vendor["holiday_cutoffs"]["valentines"] = "2026-02-05"
    result = run_analysis(
        [], date(2026, 1, 20), vendors_config=vendors, stems_config=STEMS,
        tiers_config=tiers_cfg(), calendar=CALENDAR, thresholds=THRESHOLDS,
    )
    assert len(result.upcoming_holidays) == 1, result.upcoming_holidays
    holiday = result.upcoming_holidays[0]
    assert holiday.window_id == "valentines" and holiday.days_until_peak == 25, holiday
    cutoffs = {c.vendor_id: c.cutoff_date for c in holiday.vendor_cutoffs}
    assert cutoffs == {"mayesh-las-vegas": "2026-02-05"}, cutoffs
    assert "lv-floral-wholesale" in holiday.vendors_missing_cutoff


def _run():
    tests = [
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} scenario tests passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    _run()
