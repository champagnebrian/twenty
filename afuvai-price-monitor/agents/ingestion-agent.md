# Ingestion Agent Runbook — vendor quote emails → proposals

Operational runbook for the scheduled Claude session (weekly job, or ad-hoc
when Brian says "check for vendor replies"). It turns vendor quote emails
into **proposals** — never directly into the price log. Repo root for all
paths: `afuvai-price-monitor/`.

## Hard prohibitions (from spec "Gmail access scoping" + ARCHITECTURE D6)

- NEVER send, reply, forward, label, archive, or modify anything in Gmail.
  Read-only, always.
- NEVER search the general inbox. Queries are built ONLY from
  `config/vendors.json` (see below). If a vendor has no `email_domains`
  entry, it has no email path — skip it.
- NEVER edit Drive files in place; the only Drive writes allowed anywhere in
  this system are creating NEW files. Never touch the AFUVAI Expense Tracker.
- NEVER write to `data/price-log.csv` from this runbook. Parsed quotes go to
  `data/proposals.csv` as `status=proposed` only. A quote that doesn't parse
  cleanly becomes a low-confidence proposal with a `review_note` — never a
  guess in the log, never silently dropped.

## Query construction

For each vendor in `config/vendors.json` with `active: true` and non-empty
`email_domains`:

- Normal domains → `from:<domain>` (e.g. `from:mayesh.com`).
- **Full-address rule**: if the vendor's contact email is on a shared
  provider (Las Vegas Flower Market uses `lasvegasflowermarket@gmail.com`),
  query the FULL address — `from:lasvegasflowermarket@gmail.com` — never the
  bare provider domain. Matching `gmail.com` would sweep the whole inbox and
  violates scoping.
- Entries with `alias_of` are the same company as their target — no separate
  query; any results log under the target id.
- Date window: `after:<last_run date>` from `data/ingestion-state.json`
  (`last_run: null` → 30-day window on first sweep).

## Per-run procedure

1. Read `data/ingestion-state.json` → build the date window.
2. Run the scoped Gmail searches (one per vendor company). For each thread
   hit, read messages newer than the window that are FROM the vendor side.
3. For each candidate message, run the deterministic parser:
   `cd src && python3 -m pricemonitor parse-email --sender <from-address>
   --date <received YYYY-MM-DD> --body-file <saved-body.txt>
   --message-id <gmail message id> --thread-id <gmail thread id> --append`
   - `--append` writes to `data/proposals.csv` and dedupes on
     (vendor, stem, date, per-stem price) + message id, so re-running a
     window never double-appends.
   - The parser resolves vendor from the sender address via vendors.json
     (alias-aware), extracts stem/variety/grade/price/unit, normalizes to
     per-stem, and grades confidence high/medium/low.
4. Agent judgment on top of the parser (this is why a Claude session runs
   this, not cron alone): if the parser returns zero proposals for a message
   that clearly talks about prices (tables, PDFs described in text, prose
   like "roses are running about a buck ten this week"), construct the
   proposal yourself and append it with `confidence=low` and a
   `review_note` quoting the source line. If the message is genuinely not a
   quote (invoice reminder, marketing blast), skip it — zero proposals is
   correct.
5. Run the lifecycle pass: `python3 -m pricemonitor expire-proposals`
   — flips proposals to `confirmed` when a matching row has landed in the
   price log via Quick Entry (see loop below), and to `expired` after 21
   days unconfirmed.
6. Write `data/ingestion-state.json` `last_run` = now (ISO). Commit
   `data/proposals.csv` + state file with message
   `ingestion: <n> proposals from <vendors> (<window>)`.

## The confirmation loop (who confirms, and how)

Automation cannot edit the Quick Entry sheet, so **Brian's paste is the
confirmation act**:

1. Proposals surface in the weekly digest (WS5) with a pre-formatted Quick
   Entry row per proposal.
2. Brian pastes the rows he accepts into the Quick Entry Google Sheet
   (id in `config/drive.json`) — and ignores the rest.
3. The next weekly run downloads the sheet and runs `merge-sheet`; the row
   enters `data/price-log.csv`, and `expire-proposals` sees the match
   (vendor, stem, date, per-stem price) and flips the proposal to
   `confirmed`. Unpasted proposals expire after 21 days.

## Worked example 1 — clean quote (high confidence)

From `sales@mayesh.com`, 2026-07-15: "Hi Brian — this week: Garden Roses
(Juliet) $2.85/stem, Peonies Sarah Bernhardt $4.25 per stem min 30, Silver
Dollar Eucalyptus $12.50 a bunch. Prices good through 7/22."
→ 3 proposals, confidence high: garden_rose/Juliet/2.85/stem;
peony/Sarah Bernhardt/4.25/stem (note: min 30); eucalyptus/12.50/bunch →
per-stem via stems.json default bunch count; all valid_until 2026-07-22.

## Worked example 2 — messy email (low confidence, needs review)

From `info@lvfloral.com`: "prices moved a bit — roses up maybe 40-50 cents,
dahlias holding. Call me. -G"
→ Parser yields nothing usable (no absolute price). Append ONE proposal:
vendor lv-floral-wholesale, stem standard_rose, `confidence=low`,
`review_note="needs_review: relative move only ('up maybe 40-50 cents'),
no absolute price — call vendor"`, no price fields filled beyond what
exists → it will surface in the digest for Brian to chase, and expire if
ignored. Do NOT invent a price from the relative move.
