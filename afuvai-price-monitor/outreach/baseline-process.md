# Phase 0 — Baseline Capture Process

How first quotes from the 10 vendor entries become baseline rows in the price
log. Spec: `docs/afuvai-vendor-price-monitor-prompt.md` (Phase 0);
architecture: `../ARCHITECTURE.md` (D2, D6, D7).

## Why this exists

Change detection is meaningless without a first data point per (vendor, stem).
Phase 0's job is to get one confirmed quote from each vendor and tag it as the
baseline the seasonal/margin logic anchors to.

## Flow: reply → baseline row

1. **Reply arrives** in Brian's Gmail from a vendor (in response to a Phase 0
   draft, a phone call, or the Las Vegas Flower Market public shop).
2. **Extraction** — either path lands in the same place:
   - **Ingestion agent (WS3)**: scans ONLY threads matching vendor
     addresses/domains from `config/vendors.json`, parses stem/price/unit/
     grade, writes rows to `data/proposals.csv` with status `proposed`.
   - **Manual Quick Entry**: Brian pastes or types the quote into the sheet's
     Quick Entry tab (or `python -m pricemonitor add-quote`). Phone quotes use
     `phone-script.md`, which maps 1:1 to Quick Entry columns.
3. **Confirmation** — nothing enters the canonical log unconfirmed. Brian
   marks the proposal `confirmed` (or the Quick Entry row is taken as
   confirmed by construction, since he typed it).
4. **Baseline tagging** — when a confirmed row is the FIRST confirmed quote
   for its (vendor, stem) pair, the merge job writes it to
   `data/price-log.csv` with `baseline=true`. Later quotes for the same pair
   get `baseline=false`. The tag is automatic (first-row rule), not manual.
5. **Vendor baseline completeness** — a vendor's baseline is **complete when
   at least one confirmed quote exists** for it. The weekly digest lists
   vendors still at zero confirmed quotes until all are covered.

Row fields (per D1/D7): vendor, stem/variety, date, unit price, quoting unit,
normalized per-stem price, grade, source (email/phone/manual/portal),
baseline flag, plus vendor-level facts captured from the same reply: minimum
order, delivery window, payment terms, standing-order requirement, holiday
cutoffs, rep name.

Every reply also updates `config/vendors.json` (rep/contact log, terms) —
Phase 0 answers are account facts, not just prices.

## Gmail sweep findings (2026-07-17, read-only)

Scoped searches (from:/to: vendor domains and addresses only — never the
general inbox) for: lvfloral.com, fss.com, greenleafwholesale.com,
sdfsinc.com, lasvegasflowermarket@gmail.com, mayesh.com.

**Result: zero existing threads with any vendor.** No vendor has prior quote
history in this mailbox. All 10 entries start from an empty baseline; the
spec's premise ("no existing quote data from most vendors") is actually "no
existing quote data from any vendor."

## Draft status per vendor entry

| # | Vendor entry | Company | Email used | Draft |
|---|---|---|---|---|
| 1 | LV Floral Wholesale | LV Floral | info@lvfloral.com | CREATED — draft id `r-6746775826887093567` |
| 2 | Las Vegas Floral & Plant Wholesale | LV Floral (SAME company as #1 — same address/phone/site) | — | Covered by #1's draft |
| 3 | Floral Supply Syndicate — Las Vegas | FSS | none verifiable | SKIPPED — fallback: contact form https://www.fss.com/contact.php or phone (702) 222-0453; see phone-script.md. Note: FSS sells hard goods, not cut stems — expect no stem quote |
| 4 | Floral Supply Syndicate — Sparks NV | FSS | none | Covered by FSS fallback; branch possibly CLOSED (Yelp) — verify by phone (775) 331-2955 |
| 5 | Greenleaf Wholesale Florist — Sparks NV | Greenleaf | none verifiable (only an email-format pattern; not usable) | SKIPPED — fallback: phone (775) 356-3700; ask rep for direct email on the call |
| 6 | Greenleaf Wholesale Florist — Hayward CA | Greenleaf | none | Covered by Greenleaf fallback; phone (510) 471-2200; confirm they serve Las Vegas at all |
| 7 | San Diego Florist Supplies — LV Trade Center | SDFS | genew@sdfsinc.com | CREATED — draft id `r-556253340011898982` |
| 8 | Las Vegas Flower Market | LVFM | lasvegasflowermarket@gmail.com | CREATED — draft id `r6454379485306042995` |
| 9 | Mayesh Wholesale Florist — Las Vegas | Mayesh | tmetzger@mayesh.com (LOW CONFIDENCE — possibly a former manager; current manager listed elsewhere as Jacob Hunt. Verify by phone (702) 739-0418 before sending, or swap to the mayesh.com/contact-us form) | CREATED — draft id `r2959010547382611173` |
| 10 | Floral Supply Syndicate — Santa Ana/Upland (backup) | FSS | none | Covered by FSS fallback; Santa Ana (714) 541-1233, Upland (909) 946-7226 |

4 drafts cover 4 companies directly; 1 company (LV Floral) absorbs two spec
entries; 2 companies (FSS, Greenleaf) had no verifiable email and go through
`phone-script.md` / contact forms. **All drafts are unsent** — Brian reviews,
fixes anything (especially the Mayesh address), and sends.

## Public price page status (spec: confirm before building any scraper)

Only **Las Vegas Flower Market** publishes checkable public pricing
(https://lasvegasflowermarket.com/shop-now — their FAQ states listed prices
are for everybody, no license required). Every other vendor gates pricing
behind an approved account login (LV Floral, SDFS, Mayesh — confirmed from
their own pages) or publishes none (FSS, Greenleaf). The optional portal-check
path (D6.3) is therefore scoped to LVFM only. Full evidence per vendor:
`vendor-contacts.json`.

## After Phase 0

- Reply lands → proposal → confirm → baseline row (above).
- No reply in 5 business days → phone follow-up using `phone-script.md`.
- A bounced draft address (watch the Mayesh one) → phone fallback, then
  update `vendor-contacts.json` and `config/vendors.json` with the corrected
  contact.
- Baseline coverage is reported in the weekly digest until all vendors have
  at least one confirmed quote.
