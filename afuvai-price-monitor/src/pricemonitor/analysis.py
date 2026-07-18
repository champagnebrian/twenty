# Analysis orchestration (WS4 -> WS5 contract): one run_analysis() call turns
# price-log rows into everything the weekly digest needs — cross-vendor
# comparisons, flagged moves, tier margin table, stale/aging reminders, and
# upcoming holiday cutoffs. Fully typed; WS5 consumes AnalysisResult only.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pricemonitor.models import (
    CONFIG_DIR,
    PriceLogRow,
    find_stem,
    find_vendor,
    load_seasonal_calendar,
    load_stems,
    load_thresholds,
    load_tier_recipes,
    load_vendors,
)
from pricemonitor.detection import (
    FRESHNESS_AGING,
    FRESHNESS_STALE,
    PriceMove,
    classify_freshness,
    detect_moves,
    partition_current_rows,
    quote_age_days,
)
from pricemonitor.margin import (
    StemPrice,
    TierPricing,
    latest_quotes_per_vendor,
    price_all_tiers,
    select_best_prices,
)
from pricemonitor.seasonality import HolidayCutoff, upcoming_holiday_cutoffs


@dataclass
class VendorQuoteInfo:
    # One vendor's current quote for a (stem, grade), annotated with the
    # ordering-decision context from vendors.json (D8: "cheapest" must be
    # decision-ready, not just a number).
    vendor_id: str
    vendor_name: str
    grade: str
    price_per_stem: float
    quote_date: str
    age_days: int
    freshness: str
    min_order_usd: float | None
    payment_terms: str | None
    delivery_days: str | None
    delivery_window: str | None
    delivery_method: str | None
    lead_time_days: int | None
    standing_order_requirement: str | None


@dataclass
class StemComparison:
    # Only emitted for stems with >= 2 vendors holding current quotes at the
    # SAME grade — prices are never compared across grades.
    stem_id: str
    display_name: str
    grade: str
    quotes: list[VendorQuoteInfo]  # cheapest first
    cheapest: VendorQuoteInfo
    spread_pct: float


@dataclass
class QuoteReminder:
    vendor_id: str
    vendor_name: str
    stem_id: str
    grade: str
    quote_date: str
    age_days: int
    freshness: str


@dataclass
class AnalysisResult:
    as_of: str
    # True when any tier recipe is still placeholder — the digest must caveat
    # absolute dollar figures until recipes are reconciled.
    placeholder_recipes: bool
    thresholds: dict
    best_prices: list[StemPrice]
    comparisons: list[StemComparison]
    moves: list[PriceMove]
    tier_margins: list[TierPricing]
    stale_quotes: list[QuoteReminder]
    aging_quotes: list[QuoteReminder]
    upcoming_holidays: list[HolidayCutoff] = field(default_factory=list)


def _vendor_quote_info(
    row: PriceLogRow,
    vendors_config: dict,
    today: date,
    thresholds: dict,
) -> VendorQuoteInfo:
    vendor = find_vendor(vendors_config, row.vendor_id) or {}
    delivery = vendor.get("delivery") or {}
    age = quote_age_days(row.date, today)
    return VendorQuoteInfo(
        vendor_id=row.vendor_id,
        vendor_name=vendor.get("name") or row.vendor_id,
        grade=row.grade,
        price_per_stem=row.price_per_stem,
        quote_date=row.date,
        age_days=age,
        freshness=classify_freshness(age, thresholds),
        min_order_usd=vendor.get("min_order_usd"),
        payment_terms=vendor.get("payment_terms"),
        delivery_days=delivery.get("days"),
        delivery_window=delivery.get("window"),
        delivery_method=delivery.get("method"),
        lead_time_days=vendor.get("lead_time_days"),
        standing_order_requirement=vendor.get("standing_order_requirement"),
    )


def _build_comparisons(
    current_rows: list[PriceLogRow],
    vendors_config: dict,
    stems_config: dict,
    today: date,
    thresholds: dict,
) -> list[StemComparison]:
    grouped: dict[tuple[str, str], list[PriceLogRow]] = {}
    for row in latest_quotes_per_vendor(current_rows).values():
        grouped.setdefault((row.stem_id, row.grade), []).append(row)

    comparisons: list[StemComparison] = []
    for (stem_id, grade), rows in sorted(grouped.items()):
        if len({row.vendor_id for row in rows}) < 2:
            continue
        quotes = sorted(
            (_vendor_quote_info(row, vendors_config, today, thresholds) for row in rows),
            key=lambda quote: (quote.price_per_stem, quote.quote_date),
        )
        prices = [quote.price_per_stem for quote in quotes]
        stem_config = find_stem(stems_config, stem_id) or {}
        comparisons.append(
            StemComparison(
                stem_id=stem_id,
                display_name=stem_config.get("display_name") or stem_id,
                grade=grade,
                quotes=quotes,
                cheapest=quotes[0],
                spread_pct=round((max(prices) - min(prices)) / min(prices), 4),
            )
        )
    return comparisons


def _build_reminders(
    confirmed_rows: list[PriceLogRow],
    vendors_config: dict,
    today: date,
    thresholds: dict,
) -> tuple[list[QuoteReminder], list[QuoteReminder]]:
    # Remind per (vendor, stem, grade) on its LATEST quote only — a vendor who
    # re-quoted recently doesn't get nagged about superseded history.
    stale: list[QuoteReminder] = []
    aging: list[QuoteReminder] = []
    for row in latest_quotes_per_vendor(confirmed_rows).values():
        age = quote_age_days(row.date, today)
        freshness = classify_freshness(age, thresholds)
        if freshness not in (FRESHNESS_STALE, FRESHNESS_AGING):
            continue
        vendor = find_vendor(vendors_config, row.vendor_id) or {}
        reminder = QuoteReminder(
            vendor_id=row.vendor_id,
            vendor_name=vendor.get("name") or row.vendor_id,
            stem_id=row.stem_id,
            grade=row.grade,
            quote_date=row.date,
            age_days=age,
            freshness=freshness,
        )
        (stale if freshness == FRESHNESS_STALE else aging).append(reminder)
    stale.sort(key=lambda reminder: -reminder.age_days)
    aging.sort(key=lambda reminder: -reminder.age_days)
    return stale, aging


def run_analysis(
    price_log_rows: list[PriceLogRow],
    today: date,
    *,
    vendors_config: dict | None = None,
    stems_config: dict | None = None,
    tiers_config: dict | None = None,
    calendar: dict | None = None,
    thresholds: dict | None = None,
    config_dir=CONFIG_DIR,
) -> AnalysisResult:
    vendors_config = vendors_config or load_vendors(config_dir)
    stems_config = stems_config or load_stems(config_dir)
    tiers_config = tiers_config or load_tier_recipes(config_dir)
    calendar = calendar or load_seasonal_calendar(config_dir)
    thresholds = thresholds or load_thresholds(config_dir)

    confirmed = [row for row in price_log_rows if row.status == "confirmed"]
    current_rows, _stale_rows = partition_current_rows(confirmed, today, thresholds)

    best_prices = select_best_prices(current_rows)
    tier_margins = price_all_tiers(tiers_config, best_prices, thresholds)
    moves = detect_moves(
        current_rows,
        today,
        stems_config=stems_config,
        calendar=calendar,
        thresholds=thresholds,
        tiers_config=tiers_config,
        tier_pricings=tier_margins,
        best_prices=best_prices,
    )
    comparisons = _build_comparisons(current_rows, vendors_config, stems_config, today, thresholds)
    stale_quotes, aging_quotes = _build_reminders(confirmed, vendors_config, today, thresholds)
    upcoming_holidays = upcoming_holiday_cutoffs(today, calendar, vendors_config)

    return AnalysisResult(
        as_of=today.isoformat(),
        placeholder_recipes=any(tier.get("placeholder") for tier in tiers_config["tiers"]),
        thresholds=thresholds,
        best_prices=sorted(best_prices.values(), key=lambda price: (price.stem_id, price.grade)),
        comparisons=comparisons,
        moves=moves,
        tier_margins=tier_margins,
        stale_quotes=stale_quotes,
        aging_quotes=aging_quotes,
        upcoming_holidays=upcoming_holidays,
    )
