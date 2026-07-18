# Change detection (D7): quote freshness, seasonally-adjusted baselines, and
# move classification by dollar impact on tier margins — not raw percent.
# Expected seasonal lifts with margins intact are logged INFO, never alerted.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median

from pricemonitor.models import PriceLogRow, find_stem
from pricemonitor.margin import (
    StemPrice,
    TierImpact,
    TierPricing,
    tier_dollar_impacts,
)
from pricemonitor.seasonality import resolve_seasonal_context

FRESHNESS_FRESH = "fresh"
FRESHNESS_AGING = "aging"
FRESHNESS_STALE = "stale"

SEVERITY_INFO = "INFO"
SEVERITY_WATCH = "WATCH"
SEVERITY_ALERT = "ALERT"

CLASSIFICATION_EXPECTED_SEASONAL = "expected-seasonal"
CLASSIFICATION_PRICE_MOVE = "price-move"
CLASSIFICATION_MARKET_BAND_MOVE = "market-band-move"

# A raw move inside a seasonal window counts as "expected" when the observed
# price lands within this tolerance of baseline x window multiplier.
EXPECTED_SEASONAL_TOLERANCE_PCT = 0.05
# Moves smaller than this (both raw and deseasonalized) are not worth logging.
MIN_NOTEWORTHY_MOVE_PCT = 0.05


@dataclass
class SubstitutionSuggestion:
    stem_id: str
    note: str | None
    quoted: bool
    best_price_per_stem: float | None = None
    vendor_id: str | None = None
    grade: str | None = None


@dataclass
class PriceMove:
    vendor_id: str
    stem_id: str
    grade: str
    quote_date: str
    observed_price_per_stem: float
    # Trailing median of prior current quotes, divided by each quote date's
    # seasonal multiplier (the deseasonalized base).
    deseasonalized_baseline: float
    # base x the quote date's multiplier — what the price "should" be today.
    expected_price_per_stem: float
    raw_move_pct: float
    seasonal_deviation_pct: float
    delta_per_stem: float
    seasonal_multiplier: float
    window_ids: list[str]
    classification: str
    severity: str
    reasons: list[str]
    market_price_stem: bool
    custom_quote_reprice: bool
    disruption_tag: str | None = None
    tier_impacts: list[TierImpact] = field(default_factory=list)
    substitutions: list[SubstitutionSuggestion] = field(default_factory=list)


def quote_age_days(quote_date: str, today: date) -> int:
    return (today - date.fromisoformat(quote_date)).days


def classify_freshness(
    age_days: int,
    thresholds: dict,
    valid_until: str | None = None,
    today: date | None = None,
) -> str:
    # fresh < aging_days; aging_days..stale_days inclusive = aging;
    # > stale_days = stale (excluded from "current" comparisons). A quote past
    # its vendor-stated valid_until is stale regardless of age — the vendor
    # itself said the price no longer holds.
    if valid_until and today and date.fromisoformat(valid_until) < today:
        return FRESHNESS_STALE
    if age_days < thresholds["quote_aging_days"]:
        return FRESHNESS_FRESH
    if age_days > thresholds["quote_stale_days"]:
        return FRESHNESS_STALE
    return FRESHNESS_AGING


def partition_current_rows(
    rows: list[PriceLogRow],
    today: date,
    thresholds: dict,
) -> tuple[list[PriceLogRow], list[PriceLogRow]]:
    # Split confirmed rows into (current = fresh + aging, stale). Sample and
    # unconfirmed rows never participate in analysis.
    current: list[PriceLogRow] = []
    stale: list[PriceLogRow] = []
    for row in rows:
        if row.status != "confirmed":
            continue
        freshness = classify_freshness(
            quote_age_days(row.date, today), thresholds, row.valid_until, today,
        )
        (stale if freshness == FRESHNESS_STALE else current).append(row)
    return current, stale


def substitution_suggestions(
    stem_config: dict,
    best_prices: dict[tuple[str, str], StemPrice],
) -> list[SubstitutionSuggestion]:
    # Substitutes from stems.json with their current best price where quoted;
    # not-yet-tracked/unquoted substitutes surface with quoted=False.
    suggestions: list[SubstitutionSuggestion] = []
    for substitute in stem_config.get("substitutes", []):
        candidates = [
            price for (stem_id, _), price in best_prices.items()
            if stem_id == substitute["stem_id"]
        ]
        best = min(candidates, key=lambda price: price.price_per_stem) if candidates else None
        suggestions.append(
            SubstitutionSuggestion(
                stem_id=substitute["stem_id"],
                note=substitute.get("note"),
                quoted=best is not None,
                best_price_per_stem=best.price_per_stem if best else None,
                vendor_id=best.vendor_id if best else None,
                grade=best.grade if best else None,
            )
        )
    return suggestions


def detect_moves(
    current_rows: list[PriceLogRow],
    today: date,
    *,
    stems_config: dict,
    calendar: dict,
    thresholds: dict,
    tiers_config: dict,
    tier_pricings: list[TierPricing],
    best_prices: dict[tuple[str, str], StemPrice],
) -> list[PriceMove]:
    # Per (vendor, stem, grade): baseline = trailing median of prior current
    # quotes deseasonalized by each quote date's multiplier; the newest quote
    # is compared against base x its own date's multiplier.
    groups: dict[tuple[str, str, str], list[PriceLogRow]] = {}
    for row in current_rows:
        groups.setdefault((row.vendor_id, row.stem_id, row.grade), []).append(row)

    pricing_by_tier = {pricing.tier_id: pricing for pricing in tier_pricings}
    moves: list[PriceMove] = []
    for (vendor_id, stem_id, grade), rows in groups.items():
        rows = sorted(rows, key=lambda row: row.date)
        latest, priors = rows[-1], rows[:-1]
        if not priors:
            continue  # a single quote is the baseline itself, not a move

        base = median(
            row.price_per_stem
            / resolve_seasonal_context(stem_id, date.fromisoformat(row.date), calendar).multiplier
            for row in priors
        )
        context = resolve_seasonal_context(stem_id, date.fromisoformat(latest.date), calendar)
        expected = base * context.multiplier
        observed = latest.price_per_stem
        raw_move_pct = (observed - base) / base
        deviation_pct = (observed - expected) / expected
        delta_per_stem = round(observed - expected, 4)

        impacts = tier_dollar_impacts(tiers_config, stem_id, grade, delta_per_stem)
        max_impact = max((abs(impact.dollar_impact_usd) for impact in impacts), default=0.0)
        affected = [
            pricing_by_tier[impact.tier_id]
            for impact in impacts if impact.tier_id in pricing_by_tier
        ]
        # A price at or above seasonal expectation gets blamed for a margin
        # breach (>= not >: an exactly-as-expected seasonal price that still
        # blows the floor is a breach, not a quiet week). A price DROP with a
        # breached margin isn't this move's fault — tier table still shows it.
        alert_breaches = [
            pricing for pricing in affected
            if delta_per_stem >= 0 and pricing.margin is not None
            and pricing.margin < thresholds["margin_alert_below"]
        ]
        watch_breaches = [
            pricing for pricing in affected
            if delta_per_stem >= 0 and pricing.margin is not None
            and pricing.margin < thresholds["margin_watch_below"]
            and pricing not in alert_breaches
        ]
        margins_hold = all(
            pricing.margin is None or pricing.margin >= thresholds["margin_watch_below"]
            for pricing in affected
        )

        stem_config = find_stem(stems_config, stem_id) or {}
        market_price_stem = bool(stem_config.get("market_price"))
        band_move = (
            market_price_stem
            and abs(deviation_pct) >= thresholds["market_price_band_move_pct"]
        )

        reasons = [
            f"{stem_id} ({grade}) from {vendor_id}: ${observed:.2f}/stem vs expected "
            f"${expected:.2f} (deseasonalized baseline ${base:.2f} x{context.multiplier:.2f} "
            f"seasonal), raw move {raw_move_pct:+.1%}"
        ]
        severity = SEVERITY_INFO
        classification = CLASSIFICATION_PRICE_MOVE
        custom_quote_reprice = False

        if band_move:
            severity = SEVERITY_ALERT
            classification = CLASSIFICATION_MARKET_BAND_MOVE
            custom_quote_reprice = True
            reasons.append(
                f"market-price stem moved {deviation_pct:+.1%} vs seasonal expectation "
                f"(>= {thresholds['market_price_band_move_pct']:.0%} band) — "
                "custom-quote flow needs a price update"
            )
        if alert_breaches:
            severity = SEVERITY_ALERT
            for pricing in alert_breaches:
                reasons.append(
                    f"tier {pricing.tier_id} margin {pricing.margin:.3f} below alert floor "
                    f"{thresholds['margin_alert_below']:.2f}"
                )
        elif severity != SEVERITY_ALERT and watch_breaches:
            severity = SEVERITY_WATCH
            for pricing in watch_breaches:
                reasons.append(
                    f"tier {pricing.tier_id} margin {pricing.margin:.3f} below target "
                    f"{thresholds['margin_watch_below']:.2f}"
                )
        if severity == SEVERITY_INFO and max_impact >= thresholds["min_tier_dollar_impact_usd"]:
            severity = SEVERITY_WATCH
            reasons.append(
                f"tier dollar impact ${max_impact:.2f} >= "
                f"${thresholds['min_tier_dollar_impact_usd']:.2f} threshold"
            )

        if severity == SEVERITY_INFO:
            in_window_and_expected = (
                context.multiplier != 1.0
                and abs(deviation_pct) <= EXPECTED_SEASONAL_TOLERANCE_PCT
                and abs(raw_move_pct) >= MIN_NOTEWORTHY_MOVE_PCT
            )
            if in_window_and_expected:
                classification = CLASSIFICATION_EXPECTED_SEASONAL
                margin_text = (
                    "and margins hold; logged, not alerted" if margins_hold
                    else "(note: an affected tier's margin is below target for "
                         "reasons other than this move — see tier table)"
                )
                reasons.append(
                    f"within expected seasonal window "
                    f"({context.driving_window_id or ','.join(context.window_ids)}) — "
                    f"raw {raw_move_pct:+.1%} move consistent with x{context.multiplier:.2f} "
                    f"multiplier {margin_text}"
                )
            elif (
                abs(raw_move_pct) < MIN_NOTEWORTHY_MOVE_PCT
                and abs(deviation_pct) < MIN_NOTEWORTHY_MOVE_PCT
            ):
                continue  # too small to log at all

        if latest.disruption_tag:
            reasons.append(f"disruption context: {latest.disruption_tag}")

        substitutions: list[SubstitutionSuggestion] = []
        if market_price_stem and severity == SEVERITY_ALERT:
            substitutions = substitution_suggestions(stem_config, best_prices)

        moves.append(
            PriceMove(
                vendor_id=vendor_id,
                stem_id=stem_id,
                grade=grade,
                quote_date=latest.date,
                observed_price_per_stem=observed,
                deseasonalized_baseline=round(base, 4),
                expected_price_per_stem=round(expected, 4),
                raw_move_pct=round(raw_move_pct, 4),
                seasonal_deviation_pct=round(deviation_pct, 4),
                delta_per_stem=delta_per_stem,
                seasonal_multiplier=context.multiplier,
                window_ids=context.window_ids,
                classification=classification,
                severity=severity,
                reasons=reasons,
                market_price_stem=market_price_stem,
                custom_quote_reprice=custom_quote_reprice,
                disruption_tag=latest.disruption_tag,
                tier_impacts=impacts,
                substitutions=substitutions,
            )
        )

    severity_rank = {SEVERITY_ALERT: 0, SEVERITY_WATCH: 1, SEVERITY_INFO: 2}
    moves.sort(key=lambda move: (severity_rank[move.severity], move.stem_id, move.vendor_id))
    return moves
