# Phone Script — Baseline Quote by Call

For vendors with no verifiable email (FSS, Greenleaf) or unanswered drafts.
Same fields as the email template; write answers straight into the Quick
Entry columns shown in [brackets] so the call produces log-ready rows.

Phone numbers and branch caveats: `vendor-contacts.json`.

## Opening

> "Hi, this is Brian from AFUVAI — we're a floral studio in Las Vegas doing
> weekly event and bulk work. I'm setting up my wholesale sourcing and I'd
> like to open an account and get current pricing on the stems I buy most.
> Do you have a couple of minutes, or is there a sales rep I should talk to?"

If routed to a rep: get their **name and direct email** first — that fixes
the missing-email problem for future outreach. [→ vendors.json: rep_name,
rep_email]

## Price capture — per stem

Run down the list; for each, capture the four Quick Entry price columns:

> "What are you at right now on ___?"

| Stem list | Quick Entry columns to fill |
|---|---|
| Standard roses | [stem], [unit_price], [quoting_unit: per stem / bunch-of-N / box-of-N], [grade: premium / standard / economy] |
| Garden roses | same four |
| Spray roses | same four |
| Dahlias | same four |
| Peonies (in season) | same four — if out of season, note next expected availability in [notes] |
| Ranunculus | same four |
| Lisianthus | same four |
| Hydrangea | same four |
| Stock | same four |
| Eucalyptus (silver dollar / seeded) | same four |
| Leather leaf / ruscus | same four |

Prompts that keep quotes comparable:

- "Is that per stem, per bunch — how many to the bunch — or per box?"
- "What grade is that — premium, standard?"
- "Is that today's market price or does it hold for the week?" [→ notes]

Plus for every row: [vendor], [date = today], [source = phone quote],
[baseline = yes if first quote for this vendor+stem].

## Account and terms — once per call

| Question | Column |
|---|---|
| "What do you need from me to set up a wholesale account — resale license, application form?" | vendors.json: account_requirements |
| "What's your minimum order?" | [min_order] |
| "Which days do you deliver to Las Vegas, and what's the window? Or is it will-call only?" | [delivery_days], [delivery_window] — for out-of-state branches (Greenleaf Hayward, FSS CA): "Do you ship to Las Vegas at all?" |
| "Terms for new accounts — COD, or can we get to net-30?" | [payment_terms] |
| "Do I need a weekly standing order to keep pricing or account status?" | [standing_order_req] |
| "When do Valentine's and Mother's Day pre-orders cut off?" | [holiday_cutoffs] |
| "And who's my rep going forward — best email and direct line for them?" | rep_name, rep_email, rep_phone |

## Vendor-specific checks

- **FSS (any branch)**: "Do you carry fresh-cut stems, or supplies only?" —
  research says supplies only; if confirmed, log FSS as hard-goods-only and
  drop it from stem baselines. Also: "Is your Sparks store on Greg Street
  still open?"
- **Greenleaf Sparks**: confirm current address (255 Greg St Ste B vs 605
  Glendale Ave). **Greenleaf Hayward**: confirm which Hayward address is
  live and whether they serve Las Vegas.
- **Mayesh LV** (if the email bounces): "Who handles new accounts now?" —
  our address on file may be a former manager's.

## Close

> "Great — could you email me that in writing to altmannbrian@gmail.com so I
> have it on file? I'll get the account paperwork back to you right away."

Getting it in writing turns the phone quote into an email quote the WS3
ingestion agent can parse later. Log the rows in Quick Entry immediately
after the call regardless — the phone quote is valid baseline on its own
(source = phone quote).
