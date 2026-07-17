# Data model for the AFUVAI Vendor Price Monitor.
# Dataclasses + CSV row (de)serialization + validation for the three canonical
# data files (data/price-log.csv, data/proposals.csv, data/tier-price-history.csv)
# and loaders for the config/ JSON files.

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PACKAGE_ROOT / "config"
DATA_DIR = PACKAGE_ROOT / "data"

QUOTE_UNITS = ("stem", "bunch", "box")
SOURCES = ("email", "phone", "manual", "portal")
PRICE_LOG_STATUSES = ("confirmed", "sample")
PROPOSAL_STATUSES = ("proposed", "confirmed", "rejected")
GRADES = ("premium", "standard", "economy")

PRICE_LOG_COLUMNS = [
    "id", "date", "vendor_id", "stem_id", "variety", "grade",
    "quoted_price", "quote_unit", "units_per_quote_unit", "price_per_stem",
    "currency", "source", "baseline", "valid_until", "disruption_tag",
    "notes", "entered_by", "entered_at", "status",
]

PROPOSAL_COLUMNS = PRICE_LOG_COLUMNS[:-1] + [
    "gmail_thread_id", "gmail_message_id", "extracted_at", "confidence",
    "status", "review_note",
]

TIER_PRICE_HISTORY_COLUMNS = [
    "snapshot_date", "tier_id", "retail_price_usd", "computed_cogs_usd",
    "margin", "trigger", "note",
]


class ValidationError(ValueError):
    pass


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in ("true", "1", "yes", "y")


def _to_float(value: Any, column: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError as error:
        raise ValidationError(f"{column}: cannot parse number from {value!r}") from error


def _validate_iso_date(value: str | None, column: str) -> None:
    if value is None:
        return
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError(f"{column}: {value!r} is not an ISO date (YYYY-MM-DD)") from error


def normalize_price_per_stem(
    quoted_price: float,
    quote_unit: str,
    units_per_quote_unit: float | None,
    stem_id: str | None = None,
    stems_config: dict | None = None,
) -> float:
    # Per D7: everything normalizes to per-stem before comparison. When the
    # quote row does not carry a unit count, fall back to the stem's
    # bunch_default_count from stems.json (overridable per quote by design).
    if quote_unit == "stem":
        return round(quoted_price / (units_per_quote_unit or 1), 4)
    if units_per_quote_unit is None and quote_unit == "bunch" and stem_id and stems_config:
        stem = find_stem(stems_config, stem_id)
        if stem is not None:
            units_per_quote_unit = stem["units"].get("bunch_default_count")
    if not units_per_quote_unit:
        raise ValidationError(
            f"cannot normalize {quote_unit} quote for {stem_id!r}: "
            "units_per_quote_unit missing and no default available"
        )
    return round(quoted_price / units_per_quote_unit, 4)


@dataclass
class PriceLogRow:
    id: str
    date: str
    vendor_id: str
    stem_id: str
    variety: str | None
    grade: str
    quoted_price: float
    quote_unit: str
    units_per_quote_unit: float | None
    price_per_stem: float
    currency: str = "USD"
    source: str = "manual"
    baseline: bool = False
    valid_until: str | None = None
    disruption_tag: str | None = None
    notes: str | None = None
    entered_by: str | None = None
    entered_at: str | None = None
    status: str = "confirmed"

    def dedupe_key(self) -> tuple:
        # Merge dedupe key per WS2 spec: (vendor_id, stem_id, date, price_per_stem).
        return (self.vendor_id, self.stem_id, self.date, round(self.price_per_stem, 4))

    def validate(self, vendors_config: dict | None = None, stems_config: dict | None = None) -> None:
        if not self.vendor_id:
            raise ValidationError("vendor_id is required")
        if not self.stem_id:
            raise ValidationError("stem_id is required")
        _validate_iso_date(self.date, "date")
        _validate_iso_date(self.valid_until, "valid_until")
        if self.quote_unit not in QUOTE_UNITS:
            raise ValidationError(f"quote_unit {self.quote_unit!r} not one of {QUOTE_UNITS}")
        if self.source not in SOURCES:
            raise ValidationError(f"source {self.source!r} not one of {SOURCES}")
        if self.status not in PRICE_LOG_STATUSES:
            raise ValidationError(f"status {self.status!r} not one of {PRICE_LOG_STATUSES}")
        if self.grade and self.grade not in GRADES:
            raise ValidationError(f"grade {self.grade!r} not one of {GRADES}")
        if self.quoted_price is None or self.quoted_price <= 0:
            raise ValidationError("quoted_price must be > 0")
        if self.price_per_stem is None or self.price_per_stem <= 0:
            raise ValidationError("price_per_stem must be > 0")
        if vendors_config is not None and find_vendor(vendors_config, self.vendor_id) is None:
            raise ValidationError(f"unknown vendor_id {self.vendor_id!r} (not in vendors.json)")
        if stems_config is not None and find_stem(stems_config, self.stem_id) is None:
            raise ValidationError(f"unknown stem_id {self.stem_id!r} (not in stems.json)")

    def to_csv_row(self) -> dict[str, str]:
        return _to_csv_dict(self, PRICE_LOG_COLUMNS)

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "PriceLogRow":
        return cls(**_parse_common_fields(row, status_default="confirmed"))


@dataclass
class ProposalRow:
    id: str
    date: str
    vendor_id: str
    stem_id: str
    variety: str | None
    grade: str
    quoted_price: float
    quote_unit: str
    units_per_quote_unit: float | None
    price_per_stem: float
    currency: str = "USD"
    source: str = "email"
    baseline: bool = False
    valid_until: str | None = None
    disruption_tag: str | None = None
    notes: str | None = None
    entered_by: str | None = None
    entered_at: str | None = None
    gmail_thread_id: str | None = None
    gmail_message_id: str | None = None
    extracted_at: str | None = None
    confidence: float | None = None
    status: str = "proposed"
    review_note: str | None = None

    def validate(self) -> None:
        if self.status not in PROPOSAL_STATUSES:
            raise ValidationError(f"proposal status {self.status!r} not one of {PROPOSAL_STATUSES}")
        if self.quote_unit not in QUOTE_UNITS:
            raise ValidationError(f"quote_unit {self.quote_unit!r} not one of {QUOTE_UNITS}")
        if self.source not in SOURCES:
            raise ValidationError(f"source {self.source!r} not one of {SOURCES}")
        _validate_iso_date(self.date, "date")

    def to_price_log_row(self, entered_by: str = "proposal-confirm") -> PriceLogRow:
        # Only confirmed proposals may enter the canonical log (D6).
        if self.status != "confirmed":
            raise ValidationError(f"proposal {self.id} is {self.status!r}, not confirmed")
        return PriceLogRow(
            id=self.id, date=self.date, vendor_id=self.vendor_id, stem_id=self.stem_id,
            variety=self.variety, grade=self.grade, quoted_price=self.quoted_price,
            quote_unit=self.quote_unit, units_per_quote_unit=self.units_per_quote_unit,
            price_per_stem=self.price_per_stem, currency=self.currency, source=self.source,
            baseline=self.baseline, valid_until=self.valid_until,
            disruption_tag=self.disruption_tag, notes=self.notes, entered_by=entered_by,
            entered_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            status="confirmed",
        )

    def to_csv_row(self) -> dict[str, str]:
        return _to_csv_dict(self, PROPOSAL_COLUMNS)

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "ProposalRow":
        common = _parse_common_fields(row, status_default="proposed")
        return cls(
            **common,
            gmail_thread_id=_blank_to_none(row.get("gmail_thread_id")),
            gmail_message_id=_blank_to_none(row.get("gmail_message_id")),
            extracted_at=_blank_to_none(row.get("extracted_at")),
            confidence=_to_float(row.get("confidence"), "confidence"),
            review_note=_blank_to_none(row.get("review_note")),
        )


@dataclass
class TierPriceHistoryRow:
    snapshot_date: str
    tier_id: str
    retail_price_usd: float | None
    computed_cogs_usd: float | None
    margin: float | None
    trigger: str | None
    note: str | None = None

    def validate(self) -> None:
        _validate_iso_date(self.snapshot_date, "snapshot_date")
        if not self.tier_id:
            raise ValidationError("tier_id is required")

    def to_csv_row(self) -> dict[str, str]:
        return _to_csv_dict(self, TIER_PRICE_HISTORY_COLUMNS)

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "TierPriceHistoryRow":
        return cls(
            snapshot_date=(row.get("snapshot_date") or "").strip(),
            tier_id=(row.get("tier_id") or "").strip(),
            retail_price_usd=_to_float(row.get("retail_price_usd"), "retail_price_usd"),
            computed_cogs_usd=_to_float(row.get("computed_cogs_usd"), "computed_cogs_usd"),
            margin=_to_float(row.get("margin"), "margin"),
            trigger=_blank_to_none(row.get("trigger")),
            note=_blank_to_none(row.get("note")),
        )


def _parse_common_fields(row: dict[str, str], status_default: str) -> dict[str, Any]:
    return {
        "id": (row.get("id") or "").strip(),
        "date": (row.get("date") or "").strip(),
        "vendor_id": (row.get("vendor_id") or "").strip(),
        "stem_id": (row.get("stem_id") or "").strip(),
        "variety": _blank_to_none(row.get("variety")),
        "grade": (row.get("grade") or "standard").strip(),
        "quoted_price": _to_float(row.get("quoted_price"), "quoted_price"),
        "quote_unit": (row.get("quote_unit") or "stem").strip().lower(),
        "units_per_quote_unit": _to_float(row.get("units_per_quote_unit"), "units_per_quote_unit"),
        "price_per_stem": _to_float(row.get("price_per_stem"), "price_per_stem"),
        "currency": (row.get("currency") or "USD").strip().upper(),
        "source": (row.get("source") or "manual").strip().lower(),
        "baseline": _to_bool(row.get("baseline")),
        "valid_until": _blank_to_none(row.get("valid_until")),
        "disruption_tag": _blank_to_none(row.get("disruption_tag")),
        "notes": _blank_to_none(row.get("notes")),
        "entered_by": _blank_to_none(row.get("entered_by")),
        "entered_at": _blank_to_none(row.get("entered_at")),
        "status": (row.get("status") or status_default).strip().lower(),
    }


def _to_csv_dict(instance: Any, columns: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    known = {f.name for f in fields(instance)}
    for column in columns:
        if column not in known:
            values[column] = ""
            continue
        value = getattr(instance, column)
        if value is None:
            values[column] = ""
        elif isinstance(value, bool):
            values[column] = "true" if value else "false"
        elif isinstance(value, float):
            # Trim trailing zeros but keep cents-level readability.
            values[column] = f"{value:.4f}".rstrip("0").rstrip(".")
        else:
            values[column] = str(value)
    return values


# --- Config loaders -----------------------------------------------------------
# "_comment" keys are documentation; loaders strip them so callers see data only.

def _strip_comments(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_comments(v) for k, v in node.items() if not k.startswith("_comment")}
    if isinstance(node, list):
        return [_strip_comments(item) for item in node]
    return node


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return _strip_comments(json.load(handle))


def load_vendors(config_dir: Path = CONFIG_DIR) -> dict:
    config = _load_json(config_dir / "vendors.json")
    ids = [vendor["id"] for vendor in config["vendors"]]
    if len(ids) != len(set(ids)):
        raise ValidationError("vendors.json has duplicate vendor ids")
    return config


def load_stems(config_dir: Path = CONFIG_DIR) -> dict:
    config = _load_json(config_dir / "stems.json")
    ids = {stem["id"] for stem in config["stems"]}
    if len(ids) != len(config["stems"]):
        raise ValidationError("stems.json has duplicate stem ids")
    return config


def load_tier_recipes(config_dir: Path = CONFIG_DIR) -> dict:
    config = _load_json(config_dir / "tier-recipes.json")
    stems = load_stems(config_dir)
    stem_ids = {stem["id"] for stem in stems["stems"]}
    for tier in config["tiers"]:
        for item in tier["recipe"]:
            # Recipes must only reference tracked stems (unlike substitutes,
            # which may point at not-yet-tracked stems with a note).
            if item["stem_id"] not in stem_ids:
                raise ValidationError(
                    f"tier {tier['tier_id']} references untracked stem {item['stem_id']!r}"
                )
    return config


def load_seasonal_calendar(config_dir: Path = CONFIG_DIR) -> dict:
    return _load_json(config_dir / "seasonal-calendar.json")


def load_thresholds(config_dir: Path = CONFIG_DIR) -> dict:
    return _load_json(config_dir / "thresholds.json")


def find_vendor(vendors_config: dict, vendor_id: str) -> dict | None:
    for vendor in vendors_config["vendors"]:
        if vendor["id"] == vendor_id:
            return vendor
    return None


def find_stem(stems_config: dict, stem_id: str) -> dict | None:
    for stem in stems_config["stems"]:
        if stem["id"] == stem_id:
            return stem
    return None
