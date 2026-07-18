# Deterministic quote-email parser for the WS3 ingestion path (D6.2).
# Stdlib only. Input: (sender_email, subject, body_text, received_date) →
# QuoteCandidate list. The scheduled agent (agents/ingestion-agent.md) drives
# this via `python3 -m pricemonitor parse-email`; candidates become
# data/proposals.csv rows with status=proposed and NEVER touch the price log
# directly — confirmation happens through the Quick Entry sheet loop.
#
# Vendor scope is enforced by construction: matching uses ONLY vendors.json
# email_domains / full addresses. Freemail domains (gmail.com etc.) are never
# matched as domains — LVFM's gmail address matches as a full address only.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from pricemonitor.models import (
    ProposalRow,
    ValidationError,
    find_stem,
    find_vendor,
    load_stems,
    load_vendors,
    normalize_price_per_stem,
)

# Numeric scores keep proposals.csv compatible with models.ProposalRow
# (confidence is a float column); labels are what humans and the digest see.
CONFIDENCE_SCORES = {"high": 0.9, "medium": 0.6, "low": 0.3}

# Never build a domain-wide match/search term from these — matching bare
# gmail.com would pull unrelated personal mail into scope (hard constraint).
# A vendor whose contact is a freemail address matches by FULL ADDRESS only.
FREEMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "aol.com", "icloud.com", "me.com", "protonmail.com", "proton.me",
}

# Synonyms merged with stems.json display names at match time; keys must be
# stems.json ids. Multi-word phrases win over single words (longest-first).
STEM_SYNONYMS = {
    "standard_rose": ["standard roses", "roses", "rose"],
    "garden_rose": ["garden roses", "garden rose"],
    "spray_rose": ["spray roses", "spray rose"],
    "dahlia": ["dahlias"],
    "peony": ["peonies"],
    "ranunculus": ["ranunculus", "ranunculi", "ranun"],
    "lisianthus": ["lisianthus", "lizzy", "lizzies"],
    "hydrangea": ["hydrangeas"],
    "stock": ["stock"],
    "eucalyptus": [
        "eucalyptus", "silver dollar eucalyptus", "silver dollar",
        "seeded eucalyptus", "euc",
    ],
    "greenery_ruscus": ["ruscus", "italian ruscus", "israeli ruscus"],
}

GRADE_MAP = {
    "premium": "premium", "select": "premium", "fancy": "premium",
    "first": "standard", "standard": "standard",
    "utility": "economy", "economy": "economy",
}
# "first" only counts as a grade with an explicit qualifier — it is far too
# common a word otherwise ("following up first thing").
GRADE_PATTERN = re.compile(
    r"\b(?:(premium|select|fancy|standard|utility|economy)|(first)\s+(?:grade|quality))\b",
    re.IGNORECASE,
)

UNIT_WORDS = {
    "stem": "stem", "stems": "stem", "st": "stem",
    "bunch": "bunch", "bunches": "bunch", "bu": "bunch",
    "box": "box", "boxes": "box", "case": "box",
}

_PRICE = r"(?P<price>\d{1,4}(?:\.\d{1,2})?)"
# "bunch of 25 at $43.75" / "10 stems for $32"
COUNT_FIRST_PATTERN = re.compile(
    r"(?:bunch(?:es)?\s+of\s+(?P<count>\d{1,4})|(?P<count2>\d{1,4})\s*[- ]?stems?)"
    r"\s*(?:at|for|@)\s*\$?" + _PRICE,
    re.IGNORECASE,
)
# "$1.85 per stem" / "$9.50 a bunch" / "6.50/bu" / "$55 per box of 100"
UNIT_PATTERN = re.compile(
    r"\$?" + _PRICE + r"\s*(?:per|/|a|an)\s*"
    r"(?P<unit>stems?|st|bunch(?:es)?|bu|box(?:es)?|case)\b"
    r"(?:\s+of\s+(?P<count>\d{1,4}))?",
    re.IGNORECASE,
)
# "$2.10 each" / "$2.10 ea"
EACH_PATTERN = re.compile(r"\$" + _PRICE + r"\s*(?:each|ea)\b\.?", re.IGNORECASE)
# "$1.10-$1.30/stem" / "$4 to $5 per stem" — a quoted range, not two quotes.
RANGE_PATTERN = re.compile(
    r"\$?(?P<low>\d{1,4}(?:\.\d{1,2})?)\s*(?:-|–|—|\bto\b)\s*"
    r"\$?(?P<high>\d{1,4}(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
# Vendor-name words too generic to identify a competitor mention.
GENERIC_VENDOR_WORDS = {
    "wholesale", "wholesaler", "florist", "floral", "flower", "flowers",
    "supply", "supplies", "market", "plant", "trade", "center", "inc",
    "las", "vegas", "san", "diego", "sparks", "hayward", "santa", "ana",
    "upland",
}
# "$3.25" with no unit at all → unit must be inferred (low confidence).
BARE_PATTERN = re.compile(r"\$" + _PRICE + r"\b")

# Lines about money that is not a stem quote: never extract prices from them.
SKIP_LINE_PATTERN = re.compile(
    r"invoice|balance|past due|amount due|total|subtotal|remit|payment|"
    r"minimum|delivery fee|service fee|surcharge|credit|deposit|statement",
    re.IGNORECASE,
)

VARIETY_STOPWORDS = {
    "premium", "select", "fancy", "standard", "utility", "economy", "first",
    "garden", "spray", "silver", "dollar", "italian", "israeli", "seeded",
    "the", "our", "your", "fresh", "beautiful", "assorted", "wholesale",
    "also", "and", "plus", "new", "best", "hi", "hello", "dear", "thanks",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

VALID_UNTIL_PATTERN = re.compile(
    r"(?:valid|good|firm|honor(?:ed)?)\s*(?:until|through|thru|till|til|to)\s+"
    r"(?P<when>[A-Za-z]+\.?\s+\d{1,2}(?:\s*,?\s*\d{4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
    re.IGNORECASE,
)
VALID_FOR_PATTERN = re.compile(r"valid\s+for\s+(?P<days>\d{1,3})\s+days", re.IGNORECASE)


@dataclass
class QuoteCandidate:
    stem_id: str
    variety: str | None
    grade: str
    quoted_price: float
    quote_unit: str
    units_per_quote_unit: float | None
    price_per_stem: float | None
    valid_until: str | None
    confidence: str  # high | medium | low
    needs_review: str | None
    info_notes: list[str] = field(default_factory=list)
    source_line: str = ""


@dataclass
class EmailParseResult:
    vendor_id: str | None
    matched_term: str | None
    candidates: list[QuoteCandidate]


# --- Vendor scope ---------------------------------------------------------------

def sender_address(sender: str) -> str:
    match = re.search(r"<([^>]+)>", sender)
    return (match.group(1) if match else sender).strip().lower()


def iter_scoped_vendors(vendors_config: dict):
    # Hard rule: a vendor with empty email_domains has NO Gmail footprint —
    # it is skipped entirely (alias/branch entries, phone-only vendors).
    for vendor in vendors_config["vendors"]:
        if vendor.get("email_domains"):
            yield vendor


def vendor_match_terms(vendor: dict) -> tuple[list[str], list[str]]:
    # Returns (domains, full_addresses) built exclusively from vendors.json.
    # Freemail domains are dropped from the domain list; the vendor's contact
    # email is added as a full address so gmail-hosted vendors (LVFM) match
    # by exact address, never by bare gmail.com.
    domains: list[str] = []
    addresses: list[str] = []
    for entry in vendor.get("email_domains", []):
        entry = (entry or "").strip().lower()
        if not entry:
            continue
        if "@" in entry:
            addresses.append(entry)
        elif entry not in FREEMAIL_DOMAINS:
            domains.append(entry)
    contact_email = ((vendor.get("contact") or {}).get("email") or "").strip().lower()
    if contact_email and contact_email not in addresses:
        addresses.append(contact_email)
    return domains, addresses


def resolve_vendor(
    sender_email: str,
    vendors_config: dict | None = None,
) -> tuple[str, str] | None:
    # → (vendor_id, matched_term) or None for out-of-scope senders.
    # alias_of entries resolve to their target id — quotes are never logged
    # under an alias.
    vendors_config = vendors_config or load_vendors()
    address = sender_address(sender_email)
    domain = address.rsplit("@", 1)[-1] if "@" in address else ""
    for vendor in iter_scoped_vendors(vendors_config):
        domains, addresses = vendor_match_terms(vendor)
        if address in addresses:
            return vendor.get("alias_of") or vendor["id"], address
        if domain and domain in domains:
            return vendor.get("alias_of") or vendor["id"], domain
    return None


def build_gmail_queries(
    vendors_config: dict | None = None,
    after: str | None = None,
) -> dict[str, str]:
    # One Gmail query per active in-scope vendor (clean attribution). Terms
    # come exclusively from vendors.json; `after` is Gmail-format YYYY/MM/DD.
    vendors_config = vendors_config or load_vendors()
    # Terms accumulate per alias target so an alias entry with its own
    # domains WIDENS its target's query instead of clobbering it.
    terms_by_target: dict[str, list[str]] = {}
    for vendor in iter_scoped_vendors(vendors_config):
        if vendor.get("active") is False:
            continue
        domains, addresses = vendor_match_terms(vendor)
        target = vendor.get("alias_of") or vendor["id"]
        bucket = terms_by_target.setdefault(target, [])
        bucket.extend(term for term in domains + addresses if term not in bucket)
    queries: dict[str, str] = {}
    for target, terms in terms_by_target.items():
        if not terms:
            continue
        clause = terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"
        query = f"from:{clause}"
        if after:
            query += f" after:{after}"
        queries[target] = query
    return queries


# --- Stem / grade / variety matching --------------------------------------------

def _stem_phrase_map(stems_config: dict) -> dict[str, str]:
    phrases: dict[str, str] = {}
    for stem in stems_config["stems"]:
        names = {stem["display_name"].lower()}
        # "Ruscus (Greenery)" → also match "ruscus".
        names.add(re.sub(r"\s*\(.*?\)", "", stem["display_name"].lower()).strip())
        names.update(STEM_SYNONYMS.get(stem["id"], []))
        for name in names:
            if name:
                phrases[name] = stem["id"]
    return phrases


def _stem_pattern(phrases: dict[str, str]) -> re.Pattern:
    ordered = sorted(phrases, key=len, reverse=True)
    return re.compile(
        r"\b(" + "|".join(re.escape(phrase) for phrase in ordered) + r")\b",
        re.IGNORECASE,
    )


def _find_stems(line: str, pattern: re.Pattern, phrases: dict[str, str]) -> list[tuple[str, tuple[int, int]]]:
    matches = []
    for match in pattern.finditer(line):
        phrase = match.group(1).lower()
        stem_id = phrases[phrase]
        if stem_id == "stock":
            # "in stock" / "out of stock" is availability talk, not the flower.
            prefix = line[: match.start()].lower().rstrip()
            if prefix.endswith((" in", " of")) or prefix in ("in", "of"):
                continue
        matches.append((stem_id, match.span(1)))
    return matches


def _find_grades(line: str, stem_spans: list[tuple[int, int]]) -> list[tuple[str, tuple[int, int]]]:
    grades = []
    for match in GRADE_PATTERN.finditer(line):
        word = (match.group(1) or match.group(2)).lower()
        span = match.span()
        # A grade word inside a stem phrase ("Standard Roses") is not a grade.
        if any(start <= span[0] < end for start, end in stem_spans):
            continue
        grades.append((GRADE_MAP[word], span))
    return grades


def _extract_variety(line: str, stem_span: tuple[int, int]) -> str | None:
    after = line[stem_span[1]:]
    paren = re.match(r"\s*\(([^)]{2,40})\)", after)
    if paren:
        return paren.group(1).strip()
    quoted = re.match(r"\s*['‘\"]([^'’\"]{2,40})['’\"]", after)
    if quoted:
        return quoted.group(1).strip()
    before = line[: stem_span[0]]
    preceding = re.search(r"((?:[A-Z][A-Za-z'’-]+\s+){1,3})$", before)
    if preceding:
        words = preceding.group(1).split()
        if any(word.lower() in VARIETY_STOPWORDS for word in words):
            return None
        # A single capitalized word opening the line is sentence case, not a
        # variety ("Also peonies ..."); multi-word names like "Sarah
        # Bernhardt" are kept.
        if len(words) == 1 and preceding.start(1) == 0:
            return None
        return " ".join(words)
    return None


# --- Price extraction -----------------------------------------------------------

@dataclass
class _PriceMatch:
    price: float
    unit: str | None  # normalized quote unit, None = not stated
    count: float | None
    span: tuple[int, int]
    unit_inferred_nearby: bool = False
    range_note: str | None = None


def _overlaps(span: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in taken)


def _find_price_ranges(line: str) -> list[tuple[tuple[int, int], float, float]]:
    # Quoted ranges ("$1.10-$1.30/stem"). The endpoints must both look like
    # prices with the high end above the low end; date-like "10-15" pairs are
    # filtered by requiring a $ somewhere in the match.
    ranges = []
    for match in RANGE_PATTERN.finditer(line):
        if "$" not in match.group(0):
            continue
        low, high = float(match.group("low")), float(match.group("high"))
        if 0 < low < high:
            ranges.append((match.span(), low, high))
    return ranges


def _apply_ranges(
    price_matches: list["_PriceMatch"],
    ranges: list[tuple[tuple[int, int], float, float]],
) -> list["_PriceMatch"]:
    # Collapse a range to ONE match at the upper bound (conservative for cost
    # planning), flagged for review — never two confident quotes.
    if not ranges:
        return price_matches
    kept: list[_PriceMatch] = []
    for price_match in price_matches:
        containing = next((r for r in ranges if r[0][0] <= price_match.span[0] < r[0][1]), None)
        if containing is None:
            kept.append(price_match)
            continue
        _, low, high = containing
        if price_match.price == high:
            price_match.range_note = f"price range ${low:g}-${high:g} quoted; using upper bound"
            kept.append(price_match)
        # low endpoint (and any mid-match) dropped silently — covered by the note.
    return kept


def _foreign_vendor_mention(
    line: str, own_vendor_id: str, vendors_config: dict,
) -> str | None:
    # A line naming ANOTHER configured vendor is likely quoting their price
    # ("Heard Mayesh has garden roses at $2.40") — never high-confidence.
    own = find_vendor(vendors_config, own_vendor_id) or {}
    own_group = own.get("company_group") or own_vendor_id
    lowered = line.lower()
    for vendor in vendors_config.get("vendors", []):
        if (vendor.get("company_group") or vendor["id"]) == own_group:
            continue
        for word in re.findall(r"[a-z]+", vendor.get("name", "").lower()):
            if len(word) > 3 and word not in GENERIC_VENDOR_WORDS and word in lowered:
                return vendor["name"]
    return None


def _find_prices(line: str) -> list[_PriceMatch]:
    found: list[_PriceMatch] = []
    taken: list[tuple[int, int]] = []
    for match in COUNT_FIRST_PATTERN.finditer(line):
        count = match.group("count") or match.group("count2")
        found.append(_PriceMatch(
            price=float(match.group("price")), unit="bunch",
            count=float(count), span=match.span(),
        ))
        taken.append(match.span())
    for match in UNIT_PATTERN.finditer(line):
        if _overlaps(match.span(), taken):
            continue
        unit = UNIT_WORDS[match.group("unit").lower()]
        count = float(match.group("count")) if match.group("count") else None
        found.append(_PriceMatch(
            price=float(match.group("price")), unit=unit, count=count, span=match.span(),
        ))
        taken.append(match.span())
    for match in EACH_PATTERN.finditer(line):
        if _overlaps(match.span(), taken):
            continue
        found.append(_PriceMatch(
            price=float(match.group("price")), unit="stem", count=1, span=match.span(),
        ))
        taken.append(match.span())
    for match in BARE_PATTERN.finditer(line):
        if _overlaps(match.span(), taken):
            continue
        # No unit attached to the price itself; a lone unit word later in the
        # line ("$60 for the bunch") is a weak hint, still low confidence.
        unit = None
        inferred = False
        trailing = line[match.end(): match.end() + 24].lower()
        hint = re.search(r"\b(stems?|bunch(?:es)?|bu|box(?:es)?)\b", trailing)
        if hint:
            unit = UNIT_WORDS[hint.group(1)]
            inferred = True
        found.append(_PriceMatch(
            price=float(match.group("price")), unit=unit, count=None,
            span=match.span(), unit_inferred_nearby=inferred,
        ))
        taken.append(match.span())
    found.sort(key=lambda item: item.span[0])
    return found


def _nearest(target: tuple[int, int], options: list[tuple[str, tuple[int, int]]]) -> str | None:
    if not options:
        return None
    def distance(option: tuple[str, tuple[int, int]]) -> int:
        _, span = option
        if span[1] <= target[0]:
            return target[0] - span[1]
        if target[1] <= span[0]:
            return span[0] - target[1]
        return 0
    return min(options, key=distance)[0]


# --- Candidate assembly ---------------------------------------------------------

def _build_candidate(
    stems_config: dict,
    stem_id: str,
    variety: str | None,
    grade: str,
    price_match: _PriceMatch,
    valid_until: str | None,
    source_line: str,
    cross_line: bool = False,
    foreign_vendor: str | None = None,
) -> QuoteCandidate:
    info_notes: list[str] = []
    review_notes: list[str] = []
    if getattr(price_match, "range_note", None):
        review_notes.append(price_match.range_note)
    if foreign_vendor:
        review_notes.append(
            f"line mentions another vendor ({foreign_vendor}) — price may be "
            "theirs, not the sender's"
        )
    unit = price_match.unit
    count = price_match.count
    explicit_unit = unit is not None and not price_match.unit_inferred_nearby

    if unit is None:
        unit = "stem"
        count = 1
        review_notes.append("unit not stated; assumed per stem")
    elif price_match.unit_inferred_nearby:
        review_notes.append(f"unit '{unit}' inferred from nearby text, not adjacent to price")

    defaulted = False
    if count is None and unit == "bunch":
        stem = find_stem(stems_config, stem_id)
        default = (stem or {}).get("units", {}).get("bunch_default_count")
        if default:
            count = float(default)
            defaulted = True
            info_notes.append(f"units_per_quote_unit defaulted to {default} (stems.json)")
    if unit == "stem" and count is None:
        count = 1

    try:
        price_per_stem = normalize_price_per_stem(
            price_match.price, unit, count, stem_id=stem_id, stems_config=stems_config,
        )
    except ValidationError as error:
        price_per_stem = None
        review_notes.append(f"cannot normalize to per-stem: {error}")

    if cross_line:
        review_notes.append("stem and price found on separate lines")

    if review_notes or price_per_stem is None:
        confidence = "low"
    elif explicit_unit and (unit == "stem" or not defaulted):
        confidence = "high"
    else:
        confidence = "medium"

    return QuoteCandidate(
        stem_id=stem_id, variety=variety, grade=grade,
        quoted_price=price_match.price, quote_unit=unit,
        units_per_quote_unit=count, price_per_stem=price_per_stem,
        valid_until=valid_until, confidence=confidence,
        needs_review="; ".join(review_notes) or None,
        info_notes=info_notes, source_line=source_line.strip(),
    )


def _coerce_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return datetime.fromisoformat(text).date()


def parse_valid_until(body_text: str, received: date) -> str | None:
    match = VALID_FOR_PATTERN.search(body_text)
    if match:
        return (received + timedelta(days=int(match.group("days")))).isoformat()
    match = VALID_UNTIL_PATTERN.search(body_text)
    if not match:
        return None
    when = match.group("when").strip()
    numeric = re.match(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", when)
    if numeric:
        month, day = int(numeric.group(1)), int(numeric.group(2))
        year = numeric.group(3)
        year = int(year) + (2000 if year and int(year) < 100 else 0) if year else received.year
    else:
        worded = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?$", when)
        if not worded:
            return None
        month = MONTHS.get(worded.group(1).lower()[:3])
        if not month:
            return None
        day = int(worded.group(2))
        year = int(worded.group(3)) if worded.group(3) else received.year
    try:
        result = date(year, month, day)
    except ValueError:
        return None
    if result < received:
        # "valid through Jan 5" received in December means next year.
        try:
            result = date(year + 1, month, day)
        except ValueError:
            return None
    return result.isoformat()


# --- Main entry -----------------------------------------------------------------

def parse_quote_email(
    sender_email: str,
    subject: str,
    body_text: str,
    received_date,
    vendors_config: dict | None = None,
    stems_config: dict | None = None,
) -> EmailParseResult:
    vendors_config = vendors_config or load_vendors()
    stems_config = stems_config or load_stems()
    resolved = resolve_vendor(sender_email, vendors_config)
    if resolved is None:
        # Out-of-scope sender: never parse, never propose (Gmail scoping rule).
        return EmailParseResult(vendor_id=None, matched_term=None, candidates=[])
    vendor_id, matched_term = resolved

    received = _coerce_date(received_date)
    valid_until = parse_valid_until(body_text, received)
    phrases = _stem_phrase_map(stems_config)
    pattern = _stem_pattern(phrases)

    # Subject participates as line 0 (stem context often lives there); quoted
    # reply lines (">") are Brian's own outreach echoed back — never parsed.
    lines = [subject or ""] + body_text.splitlines()

    candidates: list[QuoteCandidate] = []
    last_stem_context: tuple[int, str, str | None, str] | None = None  # (line#, stem, variety, grade)
    stems_seen = False
    prices_seen = False

    for line_index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(">"):
            continue
        stem_matches = _find_stems(stripped, pattern, phrases)
        stem_spans = [span for _, span in stem_matches]
        grade_matches = _find_grades(stripped, stem_spans)
        if stem_matches:
            stems_seen = True
        if SKIP_LINE_PATTERN.search(stripped):
            # Money talk that is not a quote (invoices, totals, fees, minimums).
            continue
        price_matches = _apply_ranges(_find_prices(stripped), _find_price_ranges(stripped))
        if price_matches:
            prices_seen = True
        foreign_vendor = _foreign_vendor_mention(stripped, vendor_id, vendors_config)

        if stem_matches and price_matches:
            for price_match in price_matches:
                stem_options = stem_matches
                stem_id = _nearest(price_match.span, stem_options)
                stem_span = next(span for sid, span in stem_matches if sid == stem_id)
                grade = _nearest(price_match.span, grade_matches) or "standard"
                variety = _extract_variety(stripped, stem_span)
                candidates.append(_build_candidate(
                    stems_config, stem_id, variety, grade, price_match,
                    valid_until, stripped, foreign_vendor=foreign_vendor,
                ))
            # Keep the stem as context: a follow-up line like "we'll do them
            # for $2.10 if you commit" still belongs to this stem.
            stem_id, stem_span = stem_matches[-1]
            last_stem_context = (
                line_index, stem_id, _extract_variety(stripped, stem_span),
                grade_matches[-1][0] if grade_matches else "standard",
            )
        elif stem_matches:
            stem_id, stem_span = stem_matches[-1]
            grade = grade_matches[-1][0] if grade_matches else "standard"
            last_stem_context = (line_index, stem_id, _extract_variety(stripped, stem_span), grade)
        elif price_matches and last_stem_context and line_index - last_stem_context[0] <= 2:
            _, stem_id, variety, grade = last_stem_context
            for price_match in price_matches:
                candidates.append(_build_candidate(
                    stems_config, stem_id, variety, grade, price_match,
                    valid_until, stripped, cross_line=True,
                    foreign_vendor=foreign_vendor,
                ))
            last_stem_context = None

    if not candidates and stems_seen and prices_seen:
        # Spec checkpoint rule: a quote-like email that doesn't parse cleanly
        # becomes a low-confidence proposal for review, never a silent drop.
        first_stem = None
        first_price = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(">") or SKIP_LINE_PATTERN.search(stripped):
                continue
            if first_stem is None:
                matches = _find_stems(stripped, pattern, phrases)
                if matches:
                    first_stem = (matches[0][0], _extract_variety(stripped, matches[0][1]), stripped)
            if first_price is None:
                prices = _find_prices(stripped)
                if prices:
                    first_price = (prices[0], stripped)
        if first_stem and first_price:
            stem_id, variety, stem_line = first_stem
            price_match, price_line = first_price
            candidate = _build_candidate(
                stems_config, stem_id, variety, "standard", price_match,
                valid_until, price_line, cross_line=stem_line != price_line,
            )
            candidate.confidence = "low"
            extra = "email did not parse cleanly; stem/price association is a guess"
            candidate.needs_review = (
                f"{candidate.needs_review}; {extra}" if candidate.needs_review else extra
            )
            candidates.append(candidate)

    return EmailParseResult(vendor_id=vendor_id, matched_term=matched_term, candidates=candidates)


def candidates_to_proposals(
    result: EmailParseResult,
    received_date,
    gmail_thread_id: str | None = None,
    gmail_message_id: str | None = None,
    entered_by: str = "ingestion-agent",
    start_sequence: int = 1,
    extracted_at: str | None = None,
) -> list[ProposalRow]:
    if result.vendor_id is None:
        return []
    received = _coerce_date(received_date)
    extracted_at = extracted_at or datetime.now().astimezone().isoformat(timespec="seconds")
    proposals: list[ProposalRow] = []
    for offset, candidate in enumerate(result.candidates):
        sequence = start_sequence + offset
        notes = list(candidate.info_notes)
        if candidate.source_line:
            notes.append(f'parsed from: "{candidate.source_line[:120]}"')
        proposal = ProposalRow(
            id=f"em-{received:%Y%m%d}-{sequence:04d}",
            date=received.isoformat(),
            vendor_id=result.vendor_id,
            stem_id=candidate.stem_id,
            variety=candidate.variety,
            grade=candidate.grade,
            quoted_price=candidate.quoted_price,
            quote_unit=candidate.quote_unit,
            units_per_quote_unit=candidate.units_per_quote_unit,
            price_per_stem=candidate.price_per_stem,
            source="email",
            valid_until=candidate.valid_until,
            notes="; ".join(notes) or None,
            entered_by=entered_by,
            gmail_thread_id=gmail_thread_id,
            gmail_message_id=gmail_message_id,
            extracted_at=extracted_at,
            confidence=CONFIDENCE_SCORES[candidate.confidence],
            status="proposed",
            review_note=candidate.needs_review,
        )
        proposal.validate()
        proposals.append(proposal)
    return proposals
