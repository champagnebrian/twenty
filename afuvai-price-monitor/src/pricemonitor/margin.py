# Tier margin model (D7): reprice the 6 bulk tiers + add-on at current best
# per-stem costs, classify margins vs thresholds.json, compute per-tier dollar
# impact of a stem price move, and snapshot tier pricing to
# data/tier-price-history.csv (price-change versioning, append-only).

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pricemonitor.models import (
    DATA_DIR,
    TIER_PRICE_HISTORY_COLUMNS,
    PriceLogRow,
    TierPriceHistoryRow,
    load_thresholds,
)

TIER_STATUS_OK = "ok"
TIER_STATUS_WATCH = "watch"
TIER_STATUS_ALERT = "alert"
# COGS computable but retail price unknown (placeholder recipes ship with
# retail_price_usd null) — margin cannot be classified yet.
TIER_STATUS_NO_RETAIL = "no-retail"
# One or more recipe stems have no current quote at any grade.
TIER_STATUS_INCOMPUTABLE = "incomputable"


@dataclass
class StemPrice:
    stem_id: str
    grade: str
    price_per_stem: float
    vendor_id: str
    quote_date: str


@dataclass
class StemCost:
    stem_id: str
    grade: str
    count: int
    unit_price_per_stem: float
    vendor_id: str
    line_cost_usd: float
    # Set when no quote existed at the recipe's grade and another grade's
    # quote was used instead — never a silent substitution.
    grade_fallback_note: str | None = None


@dataclass
class TierImpact:
    tier_id: str
    tier_name: str
    stem_count: int
    dollar_impact_usd: float


@dataclass
class TierPricing:
    tier_id: str
    name: str
    retail_price_usd: float | None
    cogs_usd: float | None
    margin: float | None
    margin_target: float
    status: str
    placeholder: bool
    missing_stems: list[str] = field(default_factory=list)
    stem_costs: list[StemCost] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def latest_quotes_per_vendor(rows: list[PriceLogRow]) -> dict[tuple[str, str, str], PriceLogRow]:
    # Most recent quote per (vendor, stem, grade); later input order wins ties.
    latest: dict[tuple[str, str, str], PriceLogRow] = {}
    for row in rows:
        key = (row.vendor_id, row.stem_id, row.grade)
        if key not in latest or row.date >= latest[key].date:
            latest[key] = row
    return latest


def select_best_prices(current_rows: list[PriceLogRow]) -> dict[tuple[str, str], StemPrice]:
    # Best current price per (stem, grade) = cheapest across each vendor's most
    # recent non-stale quote. Callers pass rows already filtered to "current"
    # (confirmed, fresh or aging — never stale) by detection/analysis.
    best: dict[tuple[str, str], StemPrice] = {}
    for row in latest_quotes_per_vendor(current_rows).values():
        key = (row.stem_id, row.grade)
        if key not in best or row.price_per_stem < best[key].price_per_stem:
            best[key] = StemPrice(
                stem_id=row.stem_id,
                grade=row.grade,
                price_per_stem=row.price_per_stem,
                vendor_id=row.vendor_id,
                quote_date=row.date,
            )
    return best


def classify_margin(margin: float, thresholds: dict) -> str:
    if margin < thresholds["margin_alert_below"]:
        return TIER_STATUS_ALERT
    if margin < thresholds["margin_watch_below"]:
        return TIER_STATUS_WATCH
    return TIER_STATUS_OK


def price_tier(tier: dict, best_prices: dict[tuple[str, str], StemPrice], thresholds: dict) -> TierPricing:
    missing: list[str] = []
    stem_costs: list[StemCost] = []
    notes: list[str] = []
    for item in tier["recipe"]:
        stem_price = best_prices.get((item["stem_id"], item["grade"]))
        fallback_note = None
        if stem_price is None:
            # Fall back to any quoted grade — with a note, never silently.
            candidates = [
                price for (stem_id, _), price in best_prices.items()
                if stem_id == item["stem_id"]
            ]
            if candidates:
                stem_price = min(candidates, key=lambda price: price.price_per_stem)
                fallback_note = (
                    f"no {item['grade']} quote for {item['stem_id']}; "
                    f"using {stem_price.grade} @ ${stem_price.price_per_stem:.2f}/stem"
                )
                notes.append(fallback_note)
            else:
                missing.append(item["stem_id"])
                continue
        stem_costs.append(
            StemCost(
                stem_id=item["stem_id"],
                grade=stem_price.grade,
                count=item["count"],
                unit_price_per_stem=stem_price.price_per_stem,
                vendor_id=stem_price.vendor_id,
                line_cost_usd=round(item["count"] * stem_price.price_per_stem, 4),
                grade_fallback_note=fallback_note,
            )
        )

    retail = tier.get("retail_price_usd")
    margin_target = tier.get("margin_target", thresholds["margin_target"])
    if missing:
        # Never silently zero a missing stem — the tier is incomputable.
        return TierPricing(
            tier_id=tier["tier_id"], name=tier["name"], retail_price_usd=retail,
            cogs_usd=None, margin=None, margin_target=margin_target,
            status=TIER_STATUS_INCOMPUTABLE, placeholder=bool(tier.get("placeholder")),
            missing_stems=missing, stem_costs=stem_costs, notes=notes,
        )
    cogs = round(sum(cost.line_cost_usd for cost in stem_costs), 4)
    if retail is None:
        margin = None
        status = TIER_STATUS_NO_RETAIL
        notes.append("retail_price_usd not set — margin unknown until reconciled")
    else:
        margin = round((retail - cogs) / retail, 4)
        status = classify_margin(margin, thresholds)
    return TierPricing(
        tier_id=tier["tier_id"], name=tier["name"], retail_price_usd=retail,
        cogs_usd=cogs, margin=margin, margin_target=margin_target, status=status,
        placeholder=bool(tier.get("placeholder")), missing_stems=[],
        stem_costs=stem_costs, notes=notes,
    )


def price_all_tiers(
    tiers_config: dict,
    best_prices: dict[tuple[str, str], StemPrice],
    thresholds: dict | None = None,
) -> list[TierPricing]:
    thresholds = thresholds or load_thresholds()
    return [price_tier(tier, best_prices, thresholds) for tier in tiers_config["tiers"]]


def tier_dollar_impacts(
    tiers_config: dict,
    stem_id: str,
    grade: str,
    delta_per_stem: float,
) -> list[TierImpact]:
    # Dollar impact of a per-stem price move on each tier using that stem at
    # that grade: recipe count x per-stem delta.
    impacts: list[TierImpact] = []
    for tier in tiers_config["tiers"]:
        count = sum(
            item["count"] for item in tier["recipe"]
            if item["stem_id"] == stem_id and item["grade"] == grade
        )
        if count:
            impacts.append(
                TierImpact(
                    tier_id=tier["tier_id"],
                    tier_name=tier["name"],
                    stem_count=count,
                    dollar_impact_usd=round(count * delta_per_stem, 2),
                )
            )
    return impacts


def snapshot_tier_pricing(
    tier_pricings: list[TierPricing],
    trigger: str,
    note: str | None = None,
    csv_path: Path = DATA_DIR / "tier-price-history.csv",
    snapshot_date: str | None = None,
) -> list[TierPriceHistoryRow]:
    # Price-change versioning (D7): append one row per tier to
    # data/tier-price-history.csv. Append-only — history is never rewritten.
    snapshot_date = snapshot_date or date.today().isoformat()
    rows = [
        TierPriceHistoryRow(
            snapshot_date=snapshot_date,
            tier_id=pricing.tier_id,
            retail_price_usd=pricing.retail_price_usd,
            computed_cogs_usd=pricing.cogs_usd,
            margin=pricing.margin,
            trigger=trigger,
            note=note,
        )
        for pricing in tier_pricings
    ]
    for row in rows:
        row.validate()
    csv_path = Path(csv_path)
    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TIER_PRICE_HISTORY_COLUMNS)
        if needs_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())
    return rows
