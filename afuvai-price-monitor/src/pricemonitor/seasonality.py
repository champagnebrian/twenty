# Seasonality logic (D7): resolve a (stem_id, date) to its seasonal window(s)
# and expected price multiplier from config/seasonal-calendar.json, and surface
# upcoming holiday order cutoffs for the weekly digest.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pricemonitor.models import load_seasonal_calendar, load_vendors


@dataclass
class SeasonalContext:
    stem_id: str
    on_date: date
    # Expected price multiplier vs off-season baseline. 1.0 = no expected lift.
    multiplier: float
    # All calendar windows active on the date (informational).
    window_ids: list[str] = field(default_factory=list)
    # The window whose multiplier won (None when multiplier is 1.0).
    driving_window_id: str | None = None


@dataclass
class VendorCutoff:
    vendor_id: str
    vendor_name: str
    cutoff_date: str


@dataclass
class HolidayCutoff:
    window_id: str
    name: str
    peak_date: date
    days_until_peak: int
    vendor_cutoffs: list[VendorCutoff] = field(default_factory=list)
    # Active vendors with no known cutoff yet — the digest nudges outreach.
    vendors_missing_cutoff: list[str] = field(default_factory=list)


def _parse_month_day(text: str) -> tuple[int, int]:
    month, day = text.split("-")
    return int(month), int(day)


def window_contains(window: dict, on_date: date) -> bool:
    # Year-agnostic month-day range, inclusive on both ends.
    start = _parse_month_day(window["start"])
    end = _parse_month_day(window["end"])
    month_day = (on_date.month, on_date.day)
    if start <= end:
        return start <= month_day <= end
    # Defensive: support a window wrapping the year boundary even though none
    # of the configured windows do today.
    return month_day >= start or month_day <= end


def active_windows(on_date: date, calendar: dict | None = None) -> list[dict]:
    calendar = calendar or load_seasonal_calendar()
    return [window for window in calendar["windows"] if window_contains(window, on_date)]


def window_multiplier(window: dict, stem_id: str) -> float:
    # stem_multipliers override default_multiplier per stem (e.g. roses x2.0
    # at Valentine's while everything else drifts x1.2).
    return window.get("stem_multipliers", {}).get(stem_id, window["default_multiplier"])


def resolve_seasonal_context(
    stem_id: str,
    on_date: date,
    calendar: dict | None = None,
) -> SeasonalContext:
    # Overlapping windows (e.g. Mother's Day inside wedding season): the
    # strongest expected lift wins — that is the market's expected price.
    windows = active_windows(on_date, calendar)
    multiplier = 1.0
    driving: str | None = None
    for window in windows:
        candidate = window_multiplier(window, stem_id)
        if candidate > multiplier:
            multiplier = candidate
            driving = window["id"]
    return SeasonalContext(
        stem_id=stem_id,
        on_date=on_date,
        multiplier=multiplier,
        window_ids=[window["id"] for window in windows],
        driving_window_id=driving,
    )


def next_peak_date(peak_month_day: str, today: date) -> date:
    month, day = _parse_month_day(peak_month_day)
    peak = date(today.year, month, day)
    if peak < today:
        peak = date(today.year + 1, month, day)
    return peak


def upcoming_holiday_cutoffs(
    today: date,
    calendar: dict | None = None,
    vendors_config: dict | None = None,
) -> list[HolidayCutoff]:
    # Holidays whose peak lands within holiday_cutoff_lead_days of today,
    # with each active vendor's pre-order cutoff where known
    # (vendors.json holiday_cutoffs, keyed by window id).
    calendar = calendar or load_seasonal_calendar()
    vendors_config = vendors_config or load_vendors()
    lead_days = calendar["holiday_cutoff_lead_days"]
    upcoming: list[HolidayCutoff] = []
    for window in calendar["windows"]:
        if not window.get("is_holiday") or not window.get("peak_date"):
            continue
        peak = next_peak_date(window["peak_date"], today)
        days_until = (peak - today).days
        if days_until > lead_days:
            continue
        cutoffs: list[VendorCutoff] = []
        missing: list[str] = []
        for vendor in vendors_config["vendors"]:
            if not vendor.get("active"):
                continue
            cutoff = (vendor.get("holiday_cutoffs") or {}).get(window["id"])
            if cutoff:
                cutoffs.append(VendorCutoff(vendor["id"], vendor["name"], cutoff))
            else:
                missing.append(vendor["id"])
        upcoming.append(
            HolidayCutoff(
                window_id=window["id"],
                name=window["name"],
                peak_date=peak,
                days_until_peak=days_until,
                vendor_cutoffs=sorted(cutoffs, key=lambda cutoff: cutoff.cutoff_date),
                vendors_missing_cutoff=missing,
            )
        )
    upcoming.sort(key=lambda holiday: holiday.days_until_peak)
    return upcoming
