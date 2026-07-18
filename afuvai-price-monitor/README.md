# AFUVAI Vendor Price Monitor — how to run and maintain it

One page. Spec: `docs/afuvai-vendor-price-monitor-prompt.md` · Design:
`ARCHITECTURE.md` · Built 2026-07-17.

## What it does

Tracks wholesale stem pricing across the 10-vendor list, normalizes
everything to per-stem, flags moves by **dollar impact on your six bulk
tiers** (seasonally aware — a Valentine's rose spike isn't an alarm), shows
the cheapest vendor per stem with min-order/terms context, and emails you a
weekly digest. Only the digest interrupts you; everything else is logged.

## Where things live

| Thing | Where |
|---|---|
| Quote entry (you) | **Quick Entry Google Sheet** — link in `config/drive.json` (Afuvai Expense Tracking folder) |
| Canonical price history | `data/price-log.csv` (append-only, git-versioned) |
| Email-parsed quotes awaiting your OK | `data/proposals.csv` → surfaced in the digest with paste-ready rows |
| Vendors / stems / substitutions / tiers / seasons / thresholds | `config/*.json` (edit = git commit) |
| Weekly digests | `reports/digest-<date>.md` + Google Doc copy + Gmail draft + Routine notification |
| Outreach status (Phase 0) | `outreach/baseline-process.md`; 4 drafts sitting in your Gmail Drafts |
| Reference workbook (10 tabs) | `AFUVAI Vendor Price Monitor.xlsx` (regenerate: `python3 -c "import sys; sys.path.insert(0,'src'); from pricemonitor.sheet_io import build_workbook; build_workbook()"`) |

## Your three touchpoints

1. **Send the outreach drafts** (Gmail → Drafts): LV Floral, SDFS, Las Vegas
   Flower Market now; Mayesh after phone-verifying the address
   ((702) 739-0418). FSS + Greenleaf go by phone — script in
   `outreach/phone-script.md`.
2. **Log quotes**: replies get parsed automatically into proposals; each
   digest gives you one pre-formatted line per proposal — paste the ones you
   accept into the Quick Entry sheet (that paste IS the confirmation).
   Phone quotes: type them straight into Quick Entry, or
   `cd src && python3 -m pricemonitor add-quote --help`.
3. **Read the weekly digest** (Monday). Quiet week = one quiet line.

## Scheduling ownership

- **Live now**: a weekly cloud Routine (Claude) runs
  `agents/ingestion-agent.md` + `agents/weekly-digest-agent.md` Mondays and
  notifies you by email/push on completion.
- **Target (Nova / Mac Mini)**: `bash scheduling/install.sh` on the Mini
  installs a launchd job (Mon 07:00, `scheduling/run-weekly.sh`). Once it
  runs green, disable the cloud Routine (ask Claude "disable the AFUVAI
  price monitor routine" or use the Routines UI).

## Maintenance

- **Fill in real tier recipes** (`config/tier-recipes.json`, currently
  `placeholder: true`) from the website repo's
  `netlify/functions/data/products.json` — margin dollar figures are
  directional until then.
- New vendor → add to `config/vendors.json` (id, email_domains, terms);
  new stem → `config/stems.json` (bunch count, substitutes, category).
- Thresholds feel noisy/quiet → `config/thresholds.json`.
- Tax time → `cd src && python3 -m pricemonitor export-accountant --year 2026`
  (categories match the Expense Tracker exactly).
- Tests: `python3 tests/test_sheet_io.py && python3 tests/test_quote_parser.py
  && python3 tests/test_analysis.py && python3 tests/test_digest.py`.

## Guardrails baked in

Gmail is read-only and vendor-scoped by construction; nothing is ever
auto-sent; the Expense Tracker is never written; nothing enters the price
log without your confirmation; price history is append-only; tier price
changes are snapshotted (`data/tier-price-history.csv`).
