"""Directory pagination: turn a market's search results into profile URLs."""

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .http import BotWallError, FetchError, ThrottledSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentListing:
    """One search-result entry, before the profile page is fetched."""

    name: str
    profile_url: str
    source: str
    # Directory rank, 1-based. Both sites sort by their own production/relevance
    # ranking by default, so rank order is the "top producer" ordering.
    rank: int


class Directory:
    """Base class for a paginated agent directory."""

    source = "unknown"
    base_url = ""

    def __init__(self, session: ThrottledSession, market_slug: str) -> None:
        self.session = session
        self.market_slug = market_slug

    def page_url(self, page: int) -> str:
        raise NotImplementedError

    def parse_listings(self, html: str, start_rank: int) -> list[AgentListing]:
        raise NotImplementedError

    def iter_listings(self, max_pages: int = 25):
        """Yield listings page by page, stopping at the first empty page."""
        rank = 0
        for page in range(1, max_pages + 1):
            url = self.page_url(page)
            logger.info("[%s] fetching directory page %s", self.source, page)
            try:
                html = self.session.get(url)
            except BotWallError:
                # Re-raise: the caller decides whether to abort the whole run.
                raise
            except FetchError as error:
                logger.warning("[%s] page %s failed: %s", self.source, page, error)
                break

            listings = self.parse_listings(html, start_rank=rank)
            if not listings:
                logger.info("[%s] no listings on page %s, stopping", self.source, page)
                break

            rank += len(listings)
            yield from listings


class ZillowDirectory(Directory):
    """Zillow "Find an Agent" directory, default (relevance/production) sort."""

    source = "zillow"
    base_url = "https://www.zillow.com"

    def page_url(self, page: int) -> str:
        path = f"/professionals/real-estate-agent-reviews/{self.market_slug}/"
        suffix = f"?page={page}" if page > 1 else ""
        return f"{self.base_url}{path}{suffix}"

    def parse_listings(self, html: str, start_rank: int) -> list[AgentListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings: list[AgentListing] = []
        seen: set[str] = set()

        # Profile URLs look like /profile/<screen-name>/
        for anchor in soup.select('a[href*="/profile/"]'):
            href = anchor.get("href") or ""
            if not re.search(r"/profile/[^/]+/?$", href):
                continue
            url = urljoin(self.base_url, href.split("?")[0])
            if url in seen:
                continue
            name = anchor.get_text(" ", strip=True)
            if not name or len(name) > 80:
                continue
            seen.add(url)
            listings.append(
                AgentListing(
                    name=name,
                    profile_url=url,
                    source=self.source,
                    rank=start_rank + len(listings) + 1,
                )
            )
        return listings


class RealtorDirectory(Directory):
    """realtor.com agent directory for a market, default ranked sort."""

    source = "realtor.com"
    base_url = "https://www.realtor.com"

    def page_url(self, page: int) -> str:
        path = f"/realestateagents/{self.market_slug}"
        suffix = f"/pg-{page}" if page > 1 else ""
        return f"{self.base_url}{path}{suffix}"

    def parse_listings(self, html: str, start_rank: int) -> list[AgentListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings: list[AgentListing] = []
        seen: set[str] = set()

        # Agent detail URLs look like /realestateagents/<slug>_<id>
        for anchor in soup.select('a[href*="/realestateagents/"]'):
            href = anchor.get("href") or ""
            if not re.search(r"/realestateagents/[a-z0-9\-]+_[a-z0-9]+", href, re.I):
                continue
            url = urljoin(self.base_url, href.split("?")[0])
            if url in seen:
                continue
            name = anchor.get_text(" ", strip=True)
            if not name or len(name) > 80:
                continue
            seen.add(url)
            listings.append(
                AgentListing(
                    name=name,
                    profile_url=url,
                    source=self.source,
                    rank=start_rank + len(listings) + 1,
                )
            )
        return listings


def normalize_name(name: str) -> str:
    """Key used to detect the same agent appearing in both directories."""
    cleaned = re.sub(r"[^a-z\s]", " ", (name or "").lower())
    cleaned = re.sub(r"\b(realtor|broker|agent|team|group|pllc|llc|inc|jr|sr|ii|iii)\b", " ", cleaned)
    return " ".join(cleaned.split())
