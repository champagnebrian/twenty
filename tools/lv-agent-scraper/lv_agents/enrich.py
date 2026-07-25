"""Single-shot fallback search and phone-type classification.

The fallback is deliberately capped at one search plus one page fetch per agent
so a directory full of gaps cannot turn into an unbounded crawl.
"""

import logging
import os
from dataclasses import dataclass

from .http import BotWallError, FetchError, ThrottledSession
from .parsers import normalize_phone, parse_profile

logger = logging.getLogger(__name__)


@dataclass
class FallbackResult:
    email: str | None = None
    phone: str | None = None
    source_url: str | None = None


class SearchProvider:
    """Wraps a search API. Direct SERP scraping is not attempted: it is both
    blocked immediately and against those services' terms."""

    def __init__(self, session: ThrottledSession) -> None:
        self.session = session
        self.serpapi_key = os.environ.get("SERPAPI_KEY")
        self.brave_key = os.environ.get("BRAVE_SEARCH_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self.serpapi_key or self.brave_key)

    def top_result_url(self, query: str) -> str | None:
        if self.serpapi_key:
            return self._serpapi(query)
        if self.brave_key:
            return self._brave(query)
        return None

    def _serpapi(self, query: str) -> str | None:
        import requests

        try:
            response = requests.get(
                "https://serpapi.com/search.json",
                params={"q": query, "api_key": self.serpapi_key, "num": 3},
                timeout=30,
            )
            response.raise_for_status()
            results = response.json().get("organic_results") or []
        except Exception as error:  # noqa: BLE001 - fallback must never abort the run
            logger.warning("serpapi lookup failed: %s", error)
            return None
        return results[0].get("link") if results else None

    def _brave(self, query: str) -> str | None:
        import requests

        try:
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 3},
                headers={"X-Subscription-Token": self.brave_key, "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            results = (response.json().get("web") or {}).get("results") or []
        except Exception as error:  # noqa: BLE001
            logger.warning("brave lookup failed: %s", error)
            return None
        return results[0].get("url") if results else None


def fallback_lookup(
    session: ThrottledSession,
    provider: SearchProvider,
    name: str,
    brokerage: str | None,
) -> FallbackResult:
    """Run exactly one search for an agent and parse the single top result."""
    if not provider.available:
        return FallbackResult()

    query = f'"{name}" "{brokerage or ""}" real estate las vegas'.replace('""', "").strip()
    url = provider.top_result_url(query)
    if not url:
        return FallbackResult()

    try:
        html = session.get(url)
    except (FetchError, BotWallError) as error:
        logger.info("fallback page fetch failed for %s: %s", name, error)
        return FallbackResult(source_url=url)

    parsed = parse_profile(html)
    phone = parsed.mobile_phone or (parsed.unlabeled_phones[0] if parsed.unlabeled_phones else None)

    return FallbackResult(
        email=parsed.email,
        phone=normalize_phone(phone) if phone else None,
        source_url=url,
    )


class PhoneClassifier:
    """Decides whether a number is a mobile, an office line, or unknown.

    Label heuristics alone cannot tell a cell from a landline, so when Twilio
    credentials are present the number is checked against Twilio Lookup's
    line-type intelligence. Without them the classification stays heuristic and
    is reported as such rather than being claimed as verified.
    """

    def __init__(self) -> None:
        self.account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        self._cache: dict[str, str] = {}

    @property
    def verification_available(self) -> bool:
        return bool(self.account_sid and self.auth_token)

    def line_type(self, phone: str) -> str | None:
        """Return 'mobile' | 'landline' | 'voip' | None via Twilio Lookup v2."""
        if not self.verification_available or not phone:
            return None
        if phone in self._cache:
            return self._cache[phone]

        import requests

        digits = "".join(character for character in phone if character.isdigit())
        e164 = f"+1{digits}" if len(digits) == 10 else f"+{digits}"
        try:
            response = requests.get(
                f"https://lookups.twilio.com/v2/PhoneNumbers/{e164}",
                params={"Fields": "line_type_intelligence"},
                auth=(self.account_sid, self.auth_token),
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json().get("line_type_intelligence") or {}
        except Exception as error:  # noqa: BLE001
            logger.warning("twilio lookup failed for %s: %s", phone, error)
            return None

        line_type = payload.get("type")
        if line_type:
            self._cache[phone] = line_type
        return line_type

    def classify(self, mobile: str | None, office: str | None, unlabeled: list[str]) -> tuple[str | None, str]:
        """Pick the best contact number and label how confident we are.

        Returns (chosen_number, phone_type) where phone_type is one of:
          verified-mobile | labeled-mobile | direct-unlabeled | office | none
        """
        candidate = mobile or (unlabeled[0] if unlabeled else None)

        if candidate:
            line_type = self.line_type(candidate)
            if line_type == "mobile":
                return candidate, "verified-mobile"
            if line_type in ("landline", "voip"):
                # Verified as not a cell; it is an office-grade line.
                return candidate, "office"

        if mobile:
            return mobile, "labeled-mobile"

        for number in unlabeled:
            # An unlabeled number that differs from the office line is the
            # agent's own listed number, which is usually their cell.
            if number != office:
                return number, "direct-unlabeled"

        if office:
            return office, "office"
        return None, "none"
