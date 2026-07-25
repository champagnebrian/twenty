#!/usr/bin/env python3
"""Scrape top-producing Las Vegas residential agents into a Google Sheet.

Pipeline: paginate Zillow's agent directory, backfill from realtor.com, fetch
each profile, parse name/phone/email/brokerage, run at most one fallback search
per agent for gaps, and append each row to the sheet as it is resolved.

Read README.md before running: the two directory sites are behind commercial
anti-bot systems and do not publish agent email addresses, which caps what this
(or any) scraper can return from them.
"""

import argparse
import logging
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass

from lv_agents.directories import (
    AgentListing,
    RealtorDirectory,
    ZillowDirectory,
    normalize_name,
)
from lv_agents.enrich import PhoneClassifier, SearchProvider, fallback_lookup
from lv_agents.http import BotWallError, FetchError, ThrottledSession
from lv_agents.parsers import parse_profile
from lv_agents.sheets import SheetWriter

logger = logging.getLogger("scrape_agents")

SHEET_TITLE = "Las Vegas Top 100 Real Estate Agents"
ZILLOW_MARKET = "las-vegas-nv"
REALTOR_MARKET = "las-vegas_nv"


@dataclass
class AgentRecord:
    name: str
    mobile_phone: str | None
    email: str | None
    brokerage: str | None
    source_tier: str
    profile_url: str
    phone_type: str


def collect_listings(session: ThrottledSession, target: int, max_pages: int) -> list[AgentListing]:
    """Gather listings across both directories, deduped by normalized name.

    Zillow's ranked directory fills the top-producer tier first; realtor.com
    backfills. Whatever remains after both is left short rather than padded.
    """
    listings: list[AgentListing] = []
    seen_names: set[str] = set()

    for directory in (
        ZillowDirectory(session, ZILLOW_MARKET),
        RealtorDirectory(session, REALTOR_MARKET),
    ):
        if len(listings) >= target:
            break
        try:
            for listing in directory.iter_listings(max_pages=max_pages):
                key = normalize_name(listing.name)
                if not key or key in seen_names:
                    continue
                seen_names.add(key)
                listings.append(listing)
                if len(listings) >= target:
                    break
        except BotWallError as error:
            logger.error("[%s] blocked by anti-bot protection: %s", directory.source, error)
            logger.error("[%s] skipping this source; see README for supported alternatives", directory.source)

    return listings


def assign_tier(listing: AgentListing, index: int, top_producer_cutoff: int) -> str:
    """Label where a row came from so the sheet shows its provenance."""
    if listing.source == "zillow" and index < top_producer_cutoff:
        return "top-producer (zillow ranked)"
    if listing.source == "zillow":
        return "broadened (zillow directory)"
    if index < top_producer_cutoff:
        return "top-producer (realtor.com ranked)"
    return "broadened (realtor.com directory)"


def resolve_agent(
    session: ThrottledSession,
    provider: SearchProvider,
    classifier: PhoneClassifier,
    listing: AgentListing,
    tier: str,
    use_fallback: bool,
) -> AgentRecord | None:
    """Fetch and parse one profile, with a single fallback search for gaps."""
    try:
        html = session.get(listing.profile_url)
    except BotWallError:
        raise
    except FetchError as error:
        logger.warning("skipping %s: %s", listing.name, error)
        return None

    profile = parse_profile(html)
    name = profile.name or listing.name
    email = profile.email
    phone, phone_type = classifier.classify(
        profile.mobile_phone, profile.office_phone, profile.unlabeled_phones
    )

    # One fallback search, only when something important is still missing.
    if use_fallback and (not email or phone_type in ("none", "office")):
        result = fallback_lookup(session, provider, name, profile.brokerage)
        if result.email and not email:
            email = result.email
        if result.phone and phone_type in ("none", "office"):
            phone, phone_type = result.phone, "fallback-search"

    return AgentRecord(
        name=name,
        mobile_phone=phone,
        email=email,
        brokerage=profile.brokerage,
        source_tier=tier,
        profile_url=listing.profile_url,
        phone_type=phone_type,
    )


def report(records: list[AgentRecord], target: int, classifier: PhoneClassifier) -> str:
    """Build the data-quality summary."""
    counts = Counter(record.phone_type for record in records)
    mobile = counts["verified-mobile"] + counts["labeled-mobile"] + counts["direct-unlabeled"] + counts["fallback-search"]
    office = counts["office"]
    none = counts["none"]
    with_email = sum(1 for record in records if record.email)

    lines = [
        "",
        "=" * 60,
        f"RESULT: {len(records)} of {target} target rows written",
        "=" * 60,
        "Phone coverage:",
        f"  mobile / direct line : {mobile}",
        f"      verified mobile  : {counts['verified-mobile']}",
        f"      labeled mobile   : {counts['labeled-mobile']}",
        f"      direct, unlabeled: {counts['direct-unlabeled']}",
        f"      via fallback     : {counts['fallback-search']}",
        f"  office line only     : {office}",
        f"  no phone at all      : {none}",
        "",
        f"Email coverage: {with_email} of {len(records)}",
        "",
        "Tier breakdown:",
    ]
    for tier, count in Counter(record.source_tier for record in records).most_common():
        lines.append(f"  {tier}: {count}")

    if not classifier.verification_available:
        lines += [
            "",
            "NOTE: TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN not set, so mobile-vs-landline",
            "was inferred from page labels, not verified against carrier data.",
            "'labeled mobile' and 'direct, unlabeled' are best-effort, not confirmed cells.",
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
                        help="path to the Google service account JSON key")
    parser.add_argument("--share-with", action="append", default=[],
                        help="email to grant writer access (repeatable)")
    parser.add_argument("--target", type=int, default=100, help="number of agents to collect")
    parser.add_argument("--top-producer-cutoff", type=int, default=100,
                        help="rows above this index count as top-producer tier")
    parser.add_argument("--max-pages", type=int, default=25, help="max directory pages per source")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=2.0)
    parser.add_argument("--no-fallback", action="store_true", help="skip the fallback web search")
    parser.add_argument("--dry-run", action="store_true",
                        help="scrape and print without touching Google Sheets")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.dry_run and not args.credentials:
        parser.error("--credentials (or GOOGLE_APPLICATION_CREDENTIALS) is required unless --dry-run")

    session = ThrottledSession(min_delay=args.min_delay, max_delay=args.max_delay)
    provider = SearchProvider(session)
    classifier = PhoneClassifier()

    if not args.no_fallback and not provider.available:
        logger.warning("no SERPAPI_KEY or BRAVE_SEARCH_API_KEY set; fallback search disabled")

    writer: SheetWriter | None = None
    already_written: set[str] = set()
    if not args.dry_run:
        writer = SheetWriter(args.credentials, SHEET_TITLE, args.share_with)
        url = writer.open_or_create()
        logger.info("sheet ready: %s", url)
        logger.info("service account: %s", writer.service_account_email)
        already_written = writer.already_written_urls()
        if already_written:
            logger.info("resuming: %s rows already present", len(already_written))

    logger.info("collecting directory listings for Las Vegas, NV")
    listings = collect_listings(session, args.target, args.max_pages)
    if not listings:
        logger.error("no listings collected; nothing to write")
        return 1
    logger.info("collected %s listings", len(listings))

    records: list[AgentRecord] = []
    for index, listing in enumerate(listings):
        if listing.profile_url in already_written:
            logger.info("[%s/%s] skip (already in sheet) %s", index + 1, len(listings), listing.name)
            continue

        tier = assign_tier(listing, index, args.top_producer_cutoff)
        logger.info("[%s/%s] %s", index + 1, len(listings), listing.name)
        try:
            record = resolve_agent(
                session, provider, classifier, listing, tier, use_fallback=not args.no_fallback
            )
        except BotWallError as error:
            logger.error("blocked mid-run: %s", error)
            logger.error("stopping; %s rows already written are preserved", len(records))
            break

        if record is None:
            continue

        records.append(record)
        if writer is not None:
            writer.append_agent(asdict(record))
        else:
            print(asdict(record))

    print(report(records, args.target, classifier))
    return 0


if __name__ == "__main__":
    sys.exit(main())
