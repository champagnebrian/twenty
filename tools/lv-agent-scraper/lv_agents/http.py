"""Polite HTTP session: rate limiting, retries, and bot-wall detection."""

import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Substrings that mean we were served an interstitial rather than the real page.
# Zillow fronts with PerimeterX/HUMAN, realtor.com with Akamai Bot Manager.
BOT_WALL_MARKERS = (
    "px-captcha",
    "perimeterx",
    "captcha-delivery",
    "please verify you're a human",
    "access to this page has been denied",
    "reference #18.",  # Akamai deny page
    "akamai reference",
    "unusual traffic from your computer network",
)


class BotWallError(RuntimeError):
    """Raised when the origin served an anti-bot interstitial instead of content.

    Surfaced rather than swallowed: a silently-empty parse would write blank
    rows to the sheet and look like missing data instead of a blocked run.
    """


class FetchError(RuntimeError):
    """Raised when a URL could not be retrieved after the configured retries."""


class ThrottledSession:
    """requests.Session wrapper enforcing a randomized inter-request delay.

    The delay is applied before every request, not just profile fetches, so
    directory pagination is throttled on the same budget.
    """

    def __init__(
        self,
        min_delay: float = 1.0,
        max_delay: float = 2.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if min_delay > max_delay:
            raise ValueError("min_delay must be <= max_delay")
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )

    def _sleep_for_rate_limit(self) -> None:
        target_gap = random.uniform(self.min_delay, self.max_delay)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < target_gap:
            time.sleep(target_gap - elapsed)

    def get(self, url: str, **kwargs) -> str:
        """Fetch a URL and return its body text.

        Retries transient failures with exponential backoff. A bot wall is not
        transient, so it raises immediately instead of burning the retry budget.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            self._sleep_for_rate_limit()
            try:
                response = self._session.get(url, timeout=self.timeout, **kwargs)
            except requests.RequestException as error:
                last_error = error
                logger.warning("request failed (%s/%s) %s: %s", attempt + 1, self.max_retries, url, error)
            else:
                self._last_request_at = time.monotonic()
                body = response.text or ""

                if is_bot_wall(response.status_code, body):
                    raise BotWallError(
                        f"anti-bot interstitial served for {url} (HTTP {response.status_code})"
                    )

                if response.status_code == 404:
                    raise FetchError(f"404 Not Found: {url}")

                if response.ok:
                    return body

                last_error = FetchError(f"HTTP {response.status_code} for {url}")
                logger.warning("HTTP %s (%s/%s) %s", response.status_code, attempt + 1, self.max_retries, url)

            self._last_request_at = time.monotonic()
            if attempt < self.max_retries - 1:
                time.sleep(2**attempt)

        raise FetchError(f"giving up on {url}: {last_error}")


def is_bot_wall(status_code: int, body: str) -> bool:
    """Detect an anti-bot interstitial from the status code and body."""
    lowered = body.lower()
    if any(marker in lowered for marker in BOT_WALL_MARKERS):
        return True
    # A 403 with a tiny body is a deny page; a real page is never this short.
    return status_code == 403 and len(body) < 20000
