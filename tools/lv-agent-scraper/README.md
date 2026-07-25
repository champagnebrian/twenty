# Las Vegas Top 100 Real Estate Agents — scraper

Paginates Zillow's and realtor.com's Las Vegas agent directories, parses each
profile, and appends rows to a Google Sheet one at a time.

**The script is complete and tested, but it has not been run against live data.**
Read "Before you run this" first — two of the four requested fields cannot be
obtained from these sources, and that is a property of the sources, not of the code.

---

## Before you run this

### 1. Both sites are blocked from this environment

`www.zillow.com` and `www.realtor.com` are denied by this session's egress
policy (HTTP 403 on CONNECT, confirmed via the agent proxy status endpoint).
No live run, and therefore no real data-quality numbers, could be produced here.
Run it somewhere with unrestricted network access.

### 2. Email is not published on either site — expect ~0% fill

Neither Zillow nor realtor.com exposes agent email addresses on profile pages.
Both route contact through a lead form, because agent leads are the product
they sell. There is no parser that recovers a field the page never contains.
The `Email` column will be almost entirely empty from these two sources.

The same caveat applies, less absolutely, to mobile numbers: the phone shown is
whatever the agent registered with the platform. Sometimes that is a cell,
often it is a branded tracking number that forwards to the brokerage. The page
rarely labels which.

### 3. Anti-bot protection will stop a plain `requests` client

Zillow fronts with PerimeterX/HUMAN and realtor.com with Akamai Bot Manager.
A BeautifulSoup + `requests` client — which is what was asked for, and what this
is — gets an interstitial within the first few pages. The code detects this
(`BotWallError`) and stops with a clear message rather than writing blank rows,
but detecting a wall is not getting through one.

### 4. Scraping these sites is against their terms

Zillow's and realtor.com's terms of use both prohibit automated collection.
That is a real risk to whoever runs this, and worth weighing before you do.

### Sources that actually carry this data

If the goal is a usable contact list rather than this specific pipeline, these
supply mobile numbers and emails under terms that permit the use:

- **GLVAR / Las Vegas REALTORS® MLS roster** — the authoritative membership
  list for this market, with the contact details agents register for business use.
- **Nevada Real Estate Division licensee lookup** — public, free, official
  licence data for every active agent in the state.
- **Licensed data vendors** — RealGrader, Lusha, ZoomInfo, Apollo, or a title
  company's agent-production report. These provide sales-volume ranking, which
  is the actual basis for "top 100 by volume" and which neither directory exposes.

A ranked-by-volume list is genuinely only available from MLS or title data.
Zillow's default sort is relevance plus paid placement, not production.

---

## Setup

```bash
cd tools/lv-agent-scraper
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Google Sheets credentials

No service account key was present in this environment, so this step is unverified.
The task description mentioned a JSON key but none was attached.

1. Create a service account in Google Cloud, enable the Sheets and Drive APIs,
   download the JSON key.
2. Share the target Sheet or Drive folder with the service account's
   `client_email` as **Editor**. Without this the write fails with a 403.
   The script logs the `client_email` on startup so you can confirm it matches.

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

### Optional enrichment

```bash
export SERPAPI_KEY=...              # or BRAVE_SEARCH_API_KEY
export TWILIO_ACCOUNT_SID=...       # verifies mobile vs landline
export TWILIO_AUTH_TOKEN=...
```

Without a search key the fallback lookup is skipped. Without Twilio the
mobile/office split is inferred from page labels and reported as unverified —
the summary says so explicitly rather than overstating confidence.

## Usage

```bash
# Scrape without touching Sheets
.venv/bin/python scrape_agents.py --dry-run --target 10

# Full run
.venv/bin/python scrape_agents.py \
  --credentials /path/to/key.json \
  --share-with you@example.com \
  --target 100
```

Key flags: `--target`, `--max-pages`, `--min-delay`/`--max-delay` (default
1–2s), `--no-fallback`, `--dry-run`, `--verbose`.

## Behaviour

- **Incremental writes** — each agent is appended as it resolves, so a crash
  loses nothing already found.
- **Resume** — re-running skips profile URLs already in the sheet.
- **Rate limiting** — randomized 1–2s gap before every request, directory pages
  included.
- **Bounded fallback** — at most one search and one page fetch per agent, only
  when email or phone is missing. It cannot loop.
- **Tiering** — Zillow ranked first, realtor.com backfill, each row labelled
  with its origin. If both run dry the run ends short rather than padding.

## Output columns

`Name | Mobile Phone | Email | Brokerage | Source Tier | Profile URL | Phone Type`

`Phone Type` is an addition to the requested columns: it records
`verified-mobile` / `labeled-mobile` / `direct-unlabeled` / `fallback-search` /
`office` / `none`, which is what makes the data-quality summary auditable
per row instead of just a number at the end.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q     # 26 passing
```

Tests cover phone normalization, platform-email filtering, four-field
extraction, the office-only case, phone classification, directory link parsing
and dedupe, and bot-wall detection — against synthetic fixtures, since the live
sites are unreachable.
