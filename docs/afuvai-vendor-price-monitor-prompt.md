# Build Prompt: AFUVAI Wholesale Vendor Price Monitor

Use this with Claude Code (Fable 5) as a single agentic build session.

---

## Goal

Build a standing system that tracks wholesale flower pricing across AFUVAI's
vendor list over time, flags meaningful price swings on the stems that drive
margin (dahlias, peonies, roses, and any other market-price flower), and feeds
that into the existing bulk-tier margin model — without requiring me to
manually re-check vendor sites or re-key quotes.

This is infrastructure, not a one-off script. It should run unattended on a
schedule and only surface output when something needs my attention.

## Context to give the agent

- AFUVAI is a Las Vegas floral business. Bulk flower packages are priced off
  LV Floral wholesale pricing (6 tiers + add-on, ~60% margin target).
  Market-price flowers (dahlias, peonies, etc.) go through a custom-quote flow
  instead of fixed pricing.
- Existing operational pattern to match: AFUVAI Expense Tracker.xlsx in Google
  Drive, receipts folder at [Drive folder link], manual entry today. The price
  monitor should live alongside this, not as a separate disconnected tool.
- Vendor list (10): LV Floral Wholesale, Las Vegas Floral & Plant Wholesale,
  Floral Supply Syndicate (Las Vegas + Sparks), Greenleaf Wholesale Florist
  (Sparks + Hayward), San Diego Florist Supplies Inc (LV Trade Center), Las
  Vegas Flower Market, Mayesh Wholesale Florist, Floral Supply Syndicate
  (Santa Ana/Upland backup).
- Reality constraint: most of these vendors do NOT have public pricing APIs
  or scrapable price sheets. Primary data source is inbound quote emails and
  manually-entered spot checks, not live scraping. Design for that reality
  first; treat any vendor portal scraping as a bonus, not the core mechanism.

## What to architect (in this order, before writing code)

0. **Phase 0 — baseline**: before any monitoring logic runs, there is no
   existing quote data from most of the 10 vendors. First deliverable is the
   outreach batch (emails/scripts) to get a first quote from each, and a
   process for logging those first quotes as the baseline. Change detection
   is meaningless without this.
1. **Data model**: one row per (vendor, stem/variety, date, unit price, unit,
   source: email quote / phone quote / manual entry / portal). Keep it in a
   new tab in the existing Expense Tracker spreadsheet or a linked sheet —
   decide which and justify it. Also capture, where known: minimum order
   size, lead time, and delivery window per vendor (e.g. Las Vegas Flower
   Market has a $250 minimum and Mon–Sat 10am–3pm delivery) — this matters
   as much as unit price when deciding who to actually order from.
2. **Ingestion paths**:
   - Manual quick-entry (I paste in a quote I just got by phone/email)
   - Email parsing: scan Gmail for quote replies from these vendors, extract
     vendor/stem/price, propose a row for confirmation before writing
   - Optional: scheduled check of any vendor with a public price page —
     confirm first which vendors actually have one before building this path
3. **Change detection**: flag by **dollar impact on affected tier margin**,
   not raw percent — a 10% move on a cheap filler stem doesn't matter, a 5%
   move on peonies during wedding season might blow a tier's target margin.
   Build in a **seasonal baseline** (Valentine's Day, Mother's Day, wedding
   season spikes are expected and shouldn't trigger the same alert as an
   off-season anomaly) so the agent isn't crying wolf every spring.
4. **Margin linkage**: when a flagged stem is one used in the 6 bulk tiers,
   recalculate that tier's margin against the ~60% target and flag if it
   drops below a threshold.
5. **Cross-vendor comparison**: once 2+ vendors have quotes logged for the
   same stem, surface who's currently cheapest for it. This is the actual
   payoff of tracking multiple vendors — not just alerting on moves, but
   giving you switching/negotiating leverage in real time.
6. **Output**: a weekly summary (not real-time noise) — what moved, which
   tiers are affected, cheapest current vendor per tracked stem, whether the
   custom-quote flow needs a price update. Decide the surface: email digest,
   Slack-style message, or a tab in the sheet I check — pick one and explain
   the tradeoff.
7. **Scheduling owner**: this should run on a schedule through the Nova /
   Mac Mini stack, not as something I have to remember to trigger manually.

## Additional fields and behaviors to build in

- **Substitution map**: for each market-price flower (dahlias, peonies),
  list acceptable substitutes (e.g. garden roses for peonies) so a price
  spike triggers a swap suggestion, not just a margin-erosion flag.
- **Unit normalization**: vendors quote per stem, per bunch of 10/25, per
  box — normalize everything to per-stem before any cross-vendor comparison.
- **Grade/quality tagging**: log premium/standard/economy grade alongside
  price so a cheap quote isn't compared against a lower grade.
- **Holiday order-cutoff tracking**: Valentine's Day and Mother's Day have
  hard pre-order deadlines with worse pricing/availability if missed — track
  cutoff dates per vendor and surface them ahead of time.
- **Rep/contact log**: floral wholesale runs on relationships — track the
  actual person you deal with per vendor, not just the company name.
- **Payment terms**: log net-30 vs. COD per vendor; this changes real cost
  of capital and should factor into who you order from, not just unit price.
- **Standing-order requirements**: some wholesalers require a weekly minimum
  order to keep account/pricing status active — track this per vendor.
- **Retail benchmarking**: periodically check competitor LV florist retail
  pricing so a wholesale cost increase doesn't quietly price AFUVAI out of
  the local market without anyone noticing.
- **Stale-quote reminders**: auto-flag any quote older than 60–90 days
  before the system treats it as current for comparison purposes.
- **Clean accountant export**: a CSV/COGS-ready export at tax time that
  matches Expense Tracker categories exactly — no second source of truth.
- **Disruption annotations**: allow tagging a price spike with known context
  (e.g. Ecuador export disruption, holiday shipping congestion) so spikes
  have a reason attached, not just a number.
- **Gmail access scoping**: the email-parsing agent should only read
  vendor-quote threads, never the full inbox, and should never auto-send
  anything without explicit confirmation.
- **Price-change versioning**: snapshot AFUVAI's own bulk-tier pricing every
  time a margin breach forces a customer-facing price update, so there's a
  history of when and why retail pricing changed.

## Orchestration model

Run this as a multi-agent build, not a single linear session:

- **Fable 5 is the orchestrator.** It owns the architecture, breaks the build
  into independent workstreams, spawns a sub-agent per workstream, and
  integrates their output into one working system. Suggested workstream
  split: (1) vendor outreach + baseline data capture, (2) sheet/data-model
  build, (3) email-parsing ingestion agent, (4) margin/threshold/seasonality
  logic, (5) weekly digest + comparison view.
- **Every sub-agent's output gets checked before it's accepted.** For each
  workstream, spawn a paired verifier sub-agent that independently reviews
  the work against this spec — not the same agent grading its own output.
  The orchestrator only merges a workstream once its verifier signs off.
- **No approval checkpoint required to finish the build.** Do not pause to
  confirm architecture, scope, or design choices with me — make the call,
  document the reasoning, and proceed. The only pauses allowed are for
  genuinely destructive/irreversible actions (e.g. deleting existing price
  history or expense data) or a real external blocker (e.g. a vendor email
  bounces and there's no way to proceed on that workstream without new
  input from me).
- **Final output**: once all workstreams are built and verified, give me one
  consolidated summary — what was built, what each verifier checked, any
  blockers that genuinely needed me, and what's live and running.

## Constraints

- Don't build a scraper against sites that don't publish pricing — confirm
  first which of the 10 vendors actually have a checkable public price page
  before assuming that path is viable.
- No new SaaS subscriptions. Use Google Drive/Sheets + Gmail as the backend
  unless there's a clear reason not to.
- This should run without me babysitting it — checkpoint with me only for
  destructive actions (deleting price history) or genuine ambiguity (e.g. a
  quote email that doesn't parse cleanly).

## Deliverable

1. The completed system: sheet/tab structure, vendor baseline data, the
   email-parsing ingestion agent, the threshold/seasonality/margin logic,
   the cross-vendor comparison view, and the weekly digest — built and
   verified per the orchestration model above.
2. A one-page doc explaining how I trigger/maintain it going forward.
3. The consolidated build summary described in Orchestration model above.

Build straight through per the orchestration model — architecture decisions
get made and documented by the orchestrator, not pre-approved by me.
