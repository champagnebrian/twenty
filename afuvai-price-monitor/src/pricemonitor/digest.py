# Weekly digest + accountant export (WS5).
# Renders an AnalysisResult (analysis.run_analysis) plus pending proposals
# into the weekly markdown digest — the system's single push output — and
# produces the COGS/accountant CSV export that mirrors Expense Tracker
# categories exactly (stems.json expense_tracker_category).

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .analysis import AnalysisResult
from .models import (
    DATA_DIR,
    ProposalRow,
    load_stems,
    find_stem,
)

# Single source of truth for the paste-row columns: the Quick Entry sheet
# header itself. A drift between digest paste rows and the sheet would break
# the confirmation loop silently.
from .sheet_io import QUICK_ENTRY_COLUMNS as QUICK_ENTRY_PASTE_COLUMNS

SEVERITY_ORDER = {"ALERT": 0, "WATCH": 1, "INFO": 2}


def _fmt_money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "—"


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "—"


def _proposal_paste_row(proposal: ProposalRow) -> str:
    # The exact comma-separated line Brian pastes into the Quick Entry sheet;
    # pasting it (then splitting text-to-columns, or pasting cell-by-cell)
    # IS the confirmation act — see agents/ingestion-agent.md.
    values = [
        proposal.date, proposal.vendor_id, proposal.stem_id,
        proposal.variety or "", proposal.grade, f"{proposal.quoted_price:g}",
        proposal.quote_unit,
        "" if proposal.units_per_quote_unit is None else f"{proposal.units_per_quote_unit:g}",
        proposal.currency, proposal.source, "true" if proposal.baseline else "false",
        proposal.valid_until or "", proposal.disruption_tag or "",
        f"accepting proposal {proposal.id}", "brian",
    ]
    return ",".join(value.replace(",", ";") for value in values)


def render_digest(
    result: AnalysisResult,
    proposals: list[ProposalRow],
    today: date,
) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# AFUVAI Vendor Price Monitor — Weekly Digest ({today.isoformat()})")
    add("")

    flagged = [m for m in result.moves if m.severity in ("ALERT", "WATCH")]
    flagged.sort(key=lambda m: (SEVERITY_ORDER[m.severity], -abs(m.delta_per_stem)))
    pending = [p for p in proposals if p.status == "proposed"]
    alerts_summary = []
    if flagged:
        alerts_summary.append(f"{len(flagged)} price flag(s)")
    breached = [t for t in result.tier_margins if t.status in ("watch", "alert")]
    if breached:
        alerts_summary.append(f"{len(breached)} tier margin(s) below target")
    if pending:
        alerts_summary.append(f"{len(pending)} proposal(s) awaiting your confirmation")
    add("**Needs attention:** " + ("; ".join(alerts_summary) if alerts_summary else "nothing — quiet week."))
    add("")

    # 1. What moved
    add("## What moved")
    if not flagged:
        add("No moves crossed the dollar-impact or margin thresholds this week.")
    seasonal = [m for m in result.moves if m.classification == "expected-seasonal"]
    if seasonal:
        add(f"({len(seasonal)} expected-seasonal move(s) logged without alarm: "
            + ", ".join(f"{m.stem_id} @ {m.vendor_id}" for m in seasonal) + ".)")
    for move in flagged:
        impact_bits = ", ".join(
            f"{impact.tier_name}: {_fmt_money(impact.dollar_impact_usd)}"
            for impact in move.tier_impacts
        ) or "no tier uses this stem"
        add(f"- **{move.severity}** {move.stem_id} ({move.grade}) @ {move.vendor_id}: "
            f"{_fmt_money(move.observed_price_per_stem)}/stem vs expected "
            f"{_fmt_money(move.expected_price_per_stem)} "
            f"({move.raw_move_pct * 100:+.0f}% raw, {move.seasonal_deviation_pct * 100:+.0f}% vs season). "
            f"Tier impact — {impact_bits}.")
        for reason in move.reasons:
            add(f"  - {reason}")
        if move.disruption_tag:
            add(f"  - context: {move.disruption_tag}")
        if move.custom_quote_reprice:
            add("  - **custom-quote flow: reprice this stem's quote band**")
        for sub in move.substitutions:
            price = (f"{_fmt_money(sub.best_price_per_stem)}/stem via {sub.vendor_id} ({sub.grade})"
                     if sub.quoted else "no current quote")
            add(f"  - substitute: {sub.stem_id} — {price}{f' — {sub.note}' if sub.note else ''}")
    add("")

    # 2. Tier margins
    add(f"## Tier margins (target {_fmt_pct(result.thresholds.get('margin_target', 0.60))})")
    if result.placeholder_recipes:
        add("> Recipes are still PLACEHOLDER compositions — dollar figures are "
            "directional until tier-recipes.json is reconciled with the real "
            "website products.json recipes.")
    for tier in result.tier_margins:
        if tier.missing_stems:
            add(f"- {tier.name}: **incomputable** — no usable quotes for: {', '.join(tier.missing_stems)}")
            continue
        marker = {"ok": "", "watch": " ⚠ WATCH", "alert": " 🔴 ALERT"}.get(tier.status, "")
        add(f"- {tier.name}: margin {_fmt_pct(tier.margin)} "
            f"(retail {_fmt_money(tier.retail_price_usd)}, COGS {_fmt_money(tier.cogs_usd)}){marker}")
        for cost in tier.stem_costs:
            if cost.grade_fallback_note:
                add(f"  - {cost.stem_id}: {cost.grade_fallback_note}")
    add("")

    # 3. Cross-vendor comparison
    add("## Cheapest vendor per stem (fresh, same-grade quotes from 2+ vendors)")
    if not result.comparisons:
        add("Not enough multi-vendor coverage yet — needs 2+ vendors quoting the "
            "same stem at the same grade. Baseline outreach replies will unlock this.")
    for comp in result.comparisons:
        cheapest = comp.cheapest
        constraints = []
        if cheapest.min_order_usd:
            constraints.append(f"min order {_fmt_money(cheapest.min_order_usd)}")
        if cheapest.payment_terms:
            constraints.append(cheapest.payment_terms)
        if cheapest.delivery_days:
            constraints.append(f"delivery {cheapest.delivery_days} {cheapest.delivery_window or ''}".strip())
        if cheapest.standing_order_requirement:
            constraints.append(f"standing order: {cheapest.standing_order_requirement}")
        add(f"- **{comp.display_name}** ({comp.grade}): {cheapest.vendor_name} at "
            f"{_fmt_money(cheapest.price_per_stem)}/stem"
            f" ({'; '.join(constraints) if constraints else 'no known constraints'})."
            f" Spread across vendors: {comp.spread_pct * 100:.0f}%.")
        others = [q for q in comp.quotes if q.vendor_id != cheapest.vendor_id]
        for quote in others:
            add(f"  - {quote.vendor_name}: {_fmt_money(quote.price_per_stem)}/stem "
                f"({quote.freshness}, {quote.age_days}d old)")
    add("")

    # 4. Proposals awaiting confirmation
    add("## Proposals awaiting your confirmation")
    if not pending:
        add("None.")
    else:
        add("Paste the rows you accept into the Quick Entry sheet "
            "(config/drive.json → quick_entry_sheet.url); ignore the rest and "
            "they expire in 21 days. One row per line, columns:")
        add(f"`{','.join(QUICK_ENTRY_PASTE_COLUMNS)}`")
        for proposal in pending:
            note = f" — {proposal.review_note}" if proposal.review_note else ""
            confidence = f"confidence {proposal.confidence}" if proposal.confidence is not None else "confidence n/a"
            add(f"- {proposal.id}: {proposal.stem_id} @ {proposal.vendor_id}, "
                f"{_fmt_money(proposal.price_per_stem)}/stem ({confidence}){note}")
            add(f"  `{_proposal_paste_row(proposal)}`")
    add("")

    # 5. Quote freshness
    add("## Quote freshness")
    if not result.stale_quotes and not result.aging_quotes:
        add("All quotes current.")
    for reminder in result.aging_quotes:
        add(f"- AGING ({reminder.age_days}d): {reminder.stem_id} ({reminder.grade}) @ "
            f"{reminder.vendor_name} — refresh before it goes stale at "
            f"{result.thresholds.get('quote_stale_days', 90)}d.")
    for reminder in result.stale_quotes:
        add(f"- STALE ({reminder.age_days}d): {reminder.stem_id} ({reminder.grade}) @ "
            f"{reminder.vendor_name} — excluded from comparisons; get a new quote.")
    add("")

    # 6. Holiday cutoffs
    add("## Upcoming holiday order cutoffs")
    if not result.upcoming_holidays:
        add("No holiday inside the lead window.")
    for holiday in result.upcoming_holidays:
        add(f"- **{holiday.name}** peaks {holiday.peak_date.isoformat()} "
            f"({holiday.days_until_peak} days out).")
        for cutoff in holiday.vendor_cutoffs:
            add(f"  - {cutoff.vendor_name}: pre-order cutoff {cutoff.cutoff_date}")
        if holiday.vendors_missing_cutoff:
            add(f"  - cutoff unknown for: {', '.join(holiday.vendors_missing_cutoff)} — "
                "ask when confirming next order.")
    add("")
    add("---")
    add("*Generated by afuvai-price-monitor. Canonical history: data/price-log.csv "
        "(git). Entry surface: the Quick Entry Google Sheet. This digest is the "
        "only scheduled output; anything not listed here needed no attention.*")
    return "\n".join(lines) + "\n"


def write_digest(
    result: AnalysisResult,
    proposals: list[ProposalRow],
    today: date,
    output_path: Path,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_digest(result, proposals, today), encoding="utf-8")
    return output_path


def write_accountant_export(
    price_log_rows,
    output_path: Path,
    stems_config: dict | None = None,
    year: int | None = None,
) -> Path:
    # COGS-ready export whose category column matches Expense Tracker
    # categories exactly. IMPORTANT CAVEAT: rows are confirmed QUOTES, not
    # purchases — this export is a reference for per-stem costs at tax time,
    # not a ledger. Actual spend lives in the Expense Tracker; never import
    # this file there as expenses (that would create the second source of
    # truth the spec forbids).
    stems_config = stems_config or load_stems()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "date", "category", "vendor_id", "description", "unit_price_per_stem",
        "quote_unit", "quoted_price", "currency", "source", "notes",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in price_log_rows:
            if row.status != "confirmed":
                continue
            if year is not None and not row.date.startswith(str(year)):
                continue
            stem = find_stem(stems_config, row.stem_id) or {}
            description = row.stem_id if not row.variety else f"{row.stem_id} ({row.variety})"
            writer.writerow({
                "date": row.date,
                "category": stem.get("expense_tracker_category", "Floral Inventory & Supplies"),
                "vendor_id": row.vendor_id,
                "description": f"{description}, {row.grade}",
                "unit_price_per_stem": f"{row.price_per_stem:.4f}",
                "quote_unit": row.quote_unit,
                "quoted_price": f"{row.quoted_price:.2f}",
                "currency": row.currency,
                "source": row.source,
                "notes": row.notes or "",
            })
    return output_path
