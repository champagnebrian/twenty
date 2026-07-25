"""Extraction of name, phone, email, and brokerage from agent profile HTML.

Both target sites render most profile data server-side into JSON blobs
(JSON-LD and a Next.js/Apollo state script) and only some of it into markup.
The JSON blobs are checked first because CSS class names on these sites are
hashed and rotate on every deploy, while the JSON keys are far more stable.
"""

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# US phone shapes: (702) 555-0134, 702-555-0134, 702.555.0134, +1 702 555 0134
PHONE_PATTERN = re.compile(
    r"(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})(?!\d)"
)

# Emails that belong to the platform or a tracking vendor, never to the agent.
EMAIL_BLOCKLIST_FRAGMENTS = (
    "@zillow.com",
    "@realtor.com",
    "@move.com",
    "@sentry.io",
    "@example.com",
    "@2x.png",
    "sentry",
    "wixpress",
    "@schema.org",
)

# Labels that mark a number as the agent's own line rather than the front desk.
MOBILE_LABEL_HINTS = ("mobile", "cell", "direct", "text", "call/text", "c:", "m:")
OFFICE_LABEL_HINTS = ("office", "brokerage", "main", "front desk", "business", "o:", "b:")


@dataclass
class ProfileData:
    """Fields scraped from one agent profile page."""

    name: str | None = None
    brokerage: str | None = None
    emails: list[str] = field(default_factory=list)
    mobile_phone: str | None = None
    office_phone: str | None = None
    # Any number found without a label telling us which line it is.
    unlabeled_phones: list[str] = field(default_factory=list)

    @property
    def email(self) -> str | None:
        return self.emails[0] if self.emails else None


def normalize_phone(raw: str) -> str | None:
    """Return a phone as (NPA) NXX-XXXX, or None if it isn't a valid US number."""
    match = PHONE_PATTERN.search(raw or "")
    if not match:
        return None
    area, exchange, line = match.groups()
    # NXX exchange codes never start with 0 or 1.
    if exchange[0] in "01":
        return None
    return f"({area}) {exchange}-{line}"


def is_plausible_agent_email(email: str) -> bool:
    lowered = email.lower()
    if any(fragment in lowered for fragment in EMAIL_BLOCKLIST_FRAGMENTS):
        return False
    # Filenames picked up by the regex from srcset/sprite attributes.
    return not lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"))


def extract_emails(soup: BeautifulSoup, html: str) -> list[str]:
    """Collect candidate agent emails, mailto links first (highest confidence)."""
    found: list[str] = []

    for anchor in soup.select('a[href^="mailto:"]'):
        address = anchor.get("href", "")[len("mailto:") :].split("?")[0].strip()
        if EMAIL_PATTERN.fullmatch(address) and is_plausible_agent_email(address):
            found.append(address)

    for match in EMAIL_PATTERN.findall(html or ""):
        if is_plausible_agent_email(match):
            found.append(match)

    deduped: list[str] = []
    for email in found:
        lowered = email.lower()
        if lowered not in deduped:
            deduped.append(lowered)
    return deduped


def _classify_labeled_phones(soup: BeautifulSoup) -> tuple[str | None, str | None, list[str]]:
    """Split phones into (mobile, office, unlabeled) using nearby label text.

    A number is attributed by the text of its container, so "Mobile: (702)..."
    lands in the mobile slot and the office contact block does not.
    """
    mobile: str | None = None
    office: str | None = None
    unlabeled: list[str] = []

    candidates: list[tuple[str, str]] = []

    for anchor in soup.select('a[href^="tel:"]'):
        number = normalize_phone(anchor.get("href", "").replace("tel:", ""))
        if not number:
            continue
        # Look at the link text plus its parent for a "Mobile"/"Office" label.
        context = " ".join(
            part for part in (anchor.get_text(" ", strip=True), _parent_text(anchor)) if part
        )
        candidates.append((number, context.lower()))

    # Elements whose own text contains both a label and a number.
    for element in soup.find_all(["li", "p", "span", "div", "td"]):
        text = element.get_text(" ", strip=True)
        if not text or len(text) > 120:
            continue
        number = normalize_phone(text)
        if number:
            candidates.append((number, text.lower()))

    for number, context in candidates:
        if any(hint in context for hint in MOBILE_LABEL_HINTS):
            mobile = mobile or number
        elif any(hint in context for hint in OFFICE_LABEL_HINTS):
            office = office or number
        elif number not in unlabeled:
            unlabeled.append(number)

    return mobile, office, unlabeled


def _parent_text(node) -> str:
    parent = node.parent
    if parent is None:
        return ""
    text = parent.get_text(" ", strip=True)
    return text if len(text) <= 160 else ""


def iter_json_ld(soup: BeautifulSoup):
    """Yield each JSON-LD object found on the page, flattening @graph wrappers."""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                yield from (node for node in graph if isinstance(node, dict))
            else:
                yield item


def _brokerage_from_json_ld(node: dict) -> str | None:
    for key in ("worksFor", "memberOf", "affiliation", "parentOrganization"):
        value = node.get(key)
        if isinstance(value, dict) and value.get("name"):
            return str(value["name"]).strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_profile(html: str) -> ProfileData:
    """Parse an agent profile page into a ProfileData record.

    Works for both Zillow and realtor.com profiles: the JSON-LD Person/RealEstateAgent
    node carries the same shape on both, and the DOM fallbacks are generic.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    data = ProfileData()

    for node in iter_json_ld(soup):
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if not any(t in ("Person", "RealEstateAgent", "LocalBusiness") for t in types if t):
            continue

        if not data.name and node.get("name"):
            data.name = str(node["name"]).strip()
        if not data.brokerage:
            data.brokerage = _brokerage_from_json_ld(node)
        if node.get("email"):
            address = str(node["email"]).replace("mailto:", "").strip()
            if EMAIL_PATTERN.fullmatch(address) and is_plausible_agent_email(address):
                data.emails.append(address.lower())
        if node.get("telephone"):
            number = normalize_phone(str(node["telephone"]))
            if number:
                data.unlabeled_phones.append(number)

    if not data.name:
        heading = soup.find("h1")
        if heading:
            data.name = heading.get_text(" ", strip=True) or None

    if not data.brokerage:
        data.brokerage = _extract_brokerage_from_dom(soup)

    mobile, office, unlabeled = _classify_labeled_phones(soup)
    data.mobile_phone = mobile
    data.office_phone = office
    for number in unlabeled + data.unlabeled_phones:
        if number not in data.unlabeled_phones:
            data.unlabeled_phones.append(number)
    data.unlabeled_phones = [
        number
        for number in dict.fromkeys(data.unlabeled_phones)
        if number not in (mobile, office)
    ]

    for email in extract_emails(soup, html):
        if email not in data.emails:
            data.emails.append(email)

    return data


def _extract_brokerage_from_dom(soup: BeautifulSoup) -> str | None:
    """Find the brokerage name from labelled markup.

    Prefers an explicit "Brokerage"/"Office" label so we get the main office name
    rather than the agent's own branded team name in the page title.
    """
    for attribute in ("data-testid", "id", "class"):
        for element in soup.find_all(attrs={attribute: re.compile(r"broker", re.I)}):
            text = element.get_text(" ", strip=True)
            if text and len(text) < 120:
                return _strip_label(text)

    label_pattern = re.compile(r"^\s*(brokerage|brokered by|office|company)\b\s*:?\s*", re.I)
    for element in soup.find_all(["li", "p", "span", "div", "dt", "th"]):
        text = element.get_text(" ", strip=True)
        if not text or len(text) > 120:
            continue
        if label_pattern.match(text):
            stripped = label_pattern.sub("", text).strip()
            if stripped:
                return stripped
            sibling = element.find_next_sibling()
            if sibling:
                sibling_text = sibling.get_text(" ", strip=True)
                if sibling_text and len(sibling_text) < 120:
                    return sibling_text
    return None


def _strip_label(text: str) -> str:
    return re.sub(r"^\s*(brokerage|brokered by|office|company)\b\s*:?\s*", "", text, flags=re.I).strip()
