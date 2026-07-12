# LeaseOwl — Native iOS Build: Full Handoff for Claude Code (Rev. 2)

**How to use this doc:** Run this in Claude Code on the Mac Mini, inside a fresh repo. Work through the phases in order. Each phase header tells you which model to run it on and why. Switch models at phase boundaries (`/model fable`, `/model sonnet`, `/model haiku`) rather than mid-phase — switching re-reads full history and costs tokens, so don't ping-pong.

**What changed in Rev. 2** (from the review pass):

- **Clerk is out; Supabase Auth is in.** The original spec's RLS policy (`user_id = auth.uid()`) only works with Supabase-issued JWTs — with Clerk it silently returns nothing and every policy would have been wrong. Supabase Auth supports Sign in with Apple and magic links natively, needs no user-sync webhook, and keeps the whole backend on one vendor. All auth references below are updated.
- **Rate limiting moved from its own late phase into Phase 6**, so the Phase 6 security review verifies something that actually exists at review time.
- **Phase 5 gains an OCR fallback** — PDFKit extracts zero text from scanned (image-only) PDFs, which describes a huge share of real leases.
- **Deadline reminders now include local notifications** (the original claimed push notifications but never built them; local notifications need no server and cover the reminder use case honestly).
- **The deletion cascade now includes Supabase Storage** (the uploaded lease PDFs — the most sensitive data in the system) and RevenueCat, not just the 5 tables.
- **The pre-submission review (now Phase 11) adds the privacy manifest and App Privacy labels** — both are App Store submission blockers, not polish.
- **The PII tokenization spec is nailed down** (structured input, broader scrub list, on-device detokenization for letters).

**One assumption carried over:** unlike the Base44 build (which deliberately excluded any AI/API calls), this native build includes the real Claude integration, since the ask was full scope start to finish without repeating the "no AI yet" constraint. If you actually want AI deferred here too, skip Phase 6's Claude-calling code and stub it the same way the Base44 build does — everything else in this doc is unaffected either way.

---

## 0. Model Routing Strategy

Three tiers, used for three different jobs. This is not "which model is smartest," it's "which job is which."

- **Fable 5** — Mythos-class, the most capable model available, at roughly double Opus 4.8's per-token cost ($10/$50 per MTok vs $5/$25). Use it only where a mistake is expensive to find later: security architecture, RLS policy design and review, anything touching PII handling, and the final pre-submission compliance pass. It sustains long investigation and catches its own mistakes — that's wasted capability on routine CRUD work.
- **Sonnet 5** — the default driver for this build. Everyday feature implementation, SwiftUI screens, SDK integrations, standard networking code. This is where most of the session time should live.
- **Haiku 4.5** — cheap, fast, ~90% of Sonnet's capability at a third of the cost ($1/$5 vs $3/$15 per MTok). Reserve it for mechanical, high-volume, low-judgment work: boilerplate test files, static data tables, repetitive UI test scaffolding. Don't run the main session on it.

**Practical mechanics:**

- Switch the whole session with `/model fable`, `/model sonnet`, `/model haiku` at the start of each phase below.
- Check your current model anytime with `/status`.
- If you're using subagents for parallel work (e.g. having one agent write tests while another builds a screen), you can pin a subagent's model directly in its frontmatter (`model: haiku`) instead of switching your main session.
- Fable 5 runs safety classifiers targeting biology and cybersecurity content; benign adjacent work (like the security-review phases here) can occasionally trip a false positive. When one fires, the request falls back to Opus 4.8, and routing stays sticky on the fallback model for roughly an hour before the primary is tried again — worth knowing since Phases 6 and 12 touch API-key/security topics. If a review phase gets stuck on fallback, just note it and continue; Opus 4.8 is an acceptable reviewer in a pinch.

Gate Fable to five checkpoints total in this build (Phases 0, 2-review, 6-review, 9-review, 11). Everything else runs on Sonnet 5 by default, with Haiku called out explicitly where it applies.

---

## 1. What's Different From the Base44 Build

- Native SwiftUI app (iOS 17+), not a webview wrapper — real native performance, local notifications for deadline reminders, real App Store distribution as a first-class app. (Remote push/APNs is deliberately out of scope for v1 — local notifications cover deadline reminders without any server infrastructure. Add APNs later only if a feature genuinely needs server-initiated push.)
- Full Claude API integration included in this pass (see assumption above).
- Reuses the same data model, brand system, and locked consent/legal copy already established — no need to re-derive those.

## 2. Stack

- **Client:** SwiftUI, iOS 17+ target, Xcode 16+, Swift 5.10+
- **Backend:** Supabase (Postgres + Row Level Security + Storage + Edge Functions + pg_cron) — one platform for DB, auth, file storage, and serverless functions
- **Auth:** Supabase Auth via the official `supabase-swift` SDK (Swift Package Manager, `https://github.com/supabase/supabase-swift`) — Sign in with Apple and magic link are both first-class, and because Supabase issues the JWTs, `auth.uid()` in RLS policies works exactly as written with zero glue code
- **AI:** Anthropic Claude API, called **only** from a Supabase Edge Function — the API key lives server-side and never ships inside the iOS binary
- **Payments:** RevenueCat + StoreKit 2 (iOS-native in-app purchases)
- **Email:** Resend, triggered by a Supabase Edge Function on a `pg_cron` schedule. The user's email is already in `auth.users` (Supabase Auth manages it), so the reminder function can read it directly — no sync webhook needed.
- **Rate limiting:** Upstash Redis, called from the Edge Functions (not from the client)
- **Analytics/monitoring:** PostHog and Sentry Swift SDKs

## 3. Data Model

Same 5 tables as the earlier spec, now living in Supabase Postgres: `users` (profile row keyed to `auth.users.id`), `documents`, `flags`, `letters`, `deadlines`. Same fields as previously defined, with `user_id` as `uuid` referencing `auth.users(id)`. RLS policy on every table: `user_id = auth.uid()`, no exceptions — and with Supabase Auth this is literally correct as written. Uploaded lease PDFs live in a Supabase Storage bucket with an equivalent per-user RLS policy on `storage.objects`. If you still have the Base44 schema doc handy, port the field list directly — it doesn't change.

---

## 4. Phased Build Plan

### Phase 0 — Architecture & Security Design
**Model: Fable 5**

- Finalize the Postgres schema and write the actual RLS policy SQL for all 5 tables **plus the Storage bucket policy** for lease uploads.
- Design the PII tokenization approach. Locked-in constraints:
  - Tenant name and property address come from **structured user input** collected before analysis (profile fields / a pre-analysis form) — never NLP-guessed from the lease text. Deterministic find-and-replace of known strings is verifiable; entity extraction is not.
  - Replacement happens **on-device, before any network call**: tenant name → `[TENANT]`, property address → `[ADDRESS]`.
  - Beyond the two named tokens, add a regex scrub pass for other high-risk PII that leases commonly contain — SSN patterns, phone numbers, email addresses — replaced with `[SSN]` / `[PHONE]` / `[EMAIL]`. Co-tenant names the user hasn't entered can't be caught deterministically; note that residual risk in the design doc rather than pretending it's solved.
  - Demand letters generate **with tokens in place**; detokenization (substituting the real name/address back) happens **on-device after the response returns**. Real PII never round-trips through the Edge Function or the Claude API.
- Design the Edge Function proxy pattern for Claude calls — the specific request/response contract the iOS app will use, so the app never sees or stores the Anthropic key. The contract should include the Upstash rate-limit check (built in Phase 6) as an explicit step in the function's request pipeline.
- Design the account-deletion Edge Function contract: verifies the caller's JWT, then (server-side, service-role) deletes rows from all 5 tables, the user's Storage objects, the RevenueCat subscriber (via their API), and finally the `auth.users` record via `auth.admin.deleteUser`. Order matters — auth user last, so a partial failure never strands data behind a deleted login.
- Finalize the two system prompts (lease analysis, demand letter) — reuse the ones already written; Fable's job here is reviewing them for anything that could leak PII into the prompt or produce non-compliant output (e.g. accidentally using "illegal" or "you will win").
- Output of this phase: a short written architecture doc plus `schema.sql`, both saved to the repo — this is what Sonnet executes against in every later phase.

### Phase 1 — Xcode Scaffold + Design System
**Model: Sonnet 5**

- New Xcode project, SwiftUI App lifecycle, iOS 17 minimum deployment target.
- Brand color assets (Navy `#1B2D4F`, Gold `#C9922A`/`#F0C040`, Warm Cream `#F5EDD8`, Warm Brown `#8B5E3C` — no green anywhere) as a Color Set/Asset Catalog.
- Tab bar shell with the 4 tabs (Home, Analyzer, Letters, Deadlines) plus a Settings entry point.
- Create the `PrivacyInfo.xcprivacy` privacy manifest stub now, in the project from day one (required-reason APIs get declared as they're adopted; Phase 11 audits it for completeness). Retrofitting it at submission time is how apps get rejected.

### Phase 2 — Supabase Backend Setup
**Model: Sonnet 5 to implement → Fable 5 to review**

- Implement the tables, RLS policies, and Storage bucket policy from Phase 0's `schema.sql` in an actual Supabase project.
- Before moving to Phase 3, switch to Fable 5 for one pass specifically checking the RLS policies — including the Storage bucket — cross-tenant data leaks are the single most expensive bug class here, worth the token cost of a dedicated review.

### Phase 3 — Supabase Auth Integration
**Model: Sonnet 5**

- Add `supabase-swift` via SPM, configure with the project URL and anon key (both are safe to ship in the client; the anon key is designed for that — RLS is the security boundary).
- Wire Sign in with Apple and magic link using Supabase Auth's built-in providers. On first sign-in, create the user's `users` profile row.
- Build the account deletion flow as the real Edge Function designed in Phase 0: JWT-verified, cascading across all 5 tables + Storage objects + RevenueCat subscriber + the `auth.users` record. This must actually work (Apple Guideline 5.1.1(v)), not be stubbed — and it's covered by a dedicated test in Phase 10.

### Phase 4 — Onboarding / Consent Flow
**Model: Sonnet 5**

- Implement the 3-screen non-skippable flow using the copy already locked in the earlier spec (Disclaimer → AI Transparency → State Selection + Consent). No new copy decisions needed here — just build it.
- Write `consented_at` to the user's row on completion.

### Phase 5 — Lease Upload + Extraction
**Model: Sonnet 5**

- Native document picker for PDF, plus a paste-text fallback.
- Use PDFKit for on-device text extraction — **with a Vision OCR fallback**. PDFKit returns empty text for image-only (scanned) PDFs, which is a very common lease format. When extraction yields empty or near-empty text, render each page to an image and run `VNRecognizeTextRequest` (still fully on-device, no external service). If OCR also fails, show an explicit "we couldn't read this document — try the paste-text option" state rather than silently proceeding with nothing.
- Save to `documents` with status `uploaded`; store the original PDF in the Storage bucket under the user's folder.

### Phase 6 — Claude Integration: Lease Analyzer + Rate Limiting
**Model: Fable 5 for the proxy + prompt wiring, Sonnet 5 for the Swift networking/UI code**

- Build the Supabase Edge Function that receives tokenized lease text + state, **checks the Upstash Redis rate limit first**, calls the Claude API with the finalized system prompt, parses the JSON response, and writes rows to `flags`. Rate limiting is built here, in this phase, inside the function — not deferred and not client-side (the client can't be trusted to self-limit). The `generate-letter` function in Phase 7 reuses the same rate-limit helper.
- Fable 5 pass specifically verifies: PII tokenization actually fires before the request leaves the device (including the regex scrub pass), the Edge Function enforces the rate limit before calling Claude, and the API key never appears in any client-visible config, bundle resource, or log.
- Sonnet 5 builds the SwiftUI results screen, the "Run Analysis" trigger, and the flag cards (severity-coded, quoted clause, plain-English explanation, action, disclaimer footer, "Generated by Claude AI · Anthropic" badge).

### Phase 7 — Demand Letter Builder
**Model: Sonnet 5**

- Reuses the Phase 6 Edge Function pattern (including the shared rate-limit helper) with the demand letter system prompt.
- Letter type selector, input form, generated letter display, copy-to-clipboard, PDF export.
- The letter comes back with `[TENANT]` / `[ADDRESS]` tokens; detokenize on-device before display/export, per the Phase 0 design.
- Enforce the free-tier 3 letters/month cap server-side (in the Edge Function, not just client-side).

### Phase 8 — Deadline Tracker + Reminders
**Model: Haiku 4.5 for the mechanical parts, Sonnet 5 for the screens and notifications**

- Haiku: generate the 6-state deposit-return-window lookup table (CA/NY/TX/FL/IL/NV) and the date-math helper functions — this is pure boilerplate with no judgment calls, a good Haiku task. Flag every state's day-count in code comments as "PLACEHOLDER — confirm exact statute with attorney before launch," matching the earlier compliance requirement.
- Sonnet: the SwiftUI screens — input form, deadline list with urgency color-coding, days-remaining calculation display.
- Sonnet: **local notification reminders** via `UNUserNotificationCenter` — schedule a local notification when a deadline is created (e.g. 7 days and 1 day before). No server, no APNs, no push certificates; permission prompt surfaces on first deadline creation. This is what makes the reminder feature real on-device; the Resend email (below) is the belt-and-suspenders channel for users who decline notification permission.
- The `pg_cron` + Resend Edge Function sends email reminders on the same schedule, reading the user's email from `auth.users`.

### Phase 9 — Payments: RevenueCat + StoreKit 2
**Model: Sonnet 5 to integrate → Fable 5 to review entitlement verification**

- StoreKit 2 product setup, RevenueCat SDK integration, paywall UI, annual-plan-default pricing screen ($12.99/mo, $89.99/yr).
- Fable 5 pass: confirm the Pro-tier gate is verified server-side (Edge Function checks the RevenueCat entitlement via webhook/API) rather than trusting a client-side flag — a client-trusted paywall is a common and cheap-to-exploit mistake.

### Phase 10 — Testing Pass
**Model: Haiku 4.5 for repetitive test scaffolding, Sonnet 5 for judgment-based test scenarios, you for physical-device testing**

- Haiku: generate the repetitive XCTest/UI test boilerplate (form validation, navigation smoke tests).
- Sonnet: write the test scenarios that actually require judgment — the free-tier letter cap edge case, the cross-user isolation test, the account-deletion cascade test (all 5 tables + Storage + auth user actually gone), and the scanned-PDF OCR fallback path.
- You: run the full flow on a physical iPhone, since some things (camera/document picker permissions, Sign in with Apple flow, notification permission prompts, real StoreKit sandbox purchases) only surface on-device.

### Phase 11 — Pre-Submission Security & Compliance Review
**Model: Fable 5**

One final high-stakes pass before App Store submission. Confirm, explicitly:

- No API keys, secrets, or credentials exist anywhere in the client binary, Info.plist, or logs. (The Supabase anon key is the one deliberate exception — it's public by design; the service-role key and Anthropic key must never appear.)
- PII tokenization fires before every single Claude-bound request, with no code path that bypasses it — including the paste-text path and the OCR path.
- RLS actually blocks cross-user access — test with two real accounts, not just policy inspection, and include Storage object access in the test.
- Account deletion cascades fully: all 5 tables, Storage objects, RevenueCat subscriber, and the `auth.users` record.
- Every AI-touching screen shows the "legal information, not legal advice" disclaimer.
- `PrivacyInfo.xcprivacy` is complete: all required-reason APIs declared, data-collection types match reality (lease documents, email, purchase history, analytics).
- App Privacy nutrition labels drafted for App Store Connect, consistent with the privacy manifest.
- Draft the App Review notes explaining the consent flow and AI disclosure for the reviewer.

---

## 5. Cost Notes

Fable 5 is gated to 5 checkpoints (Phases 0, 2-review, 6-review, 9-review, 11) rather than the whole build — those are the points where an undetected mistake (a data leak, a leaked API key, a bypassable paywall) costs far more than the token bill to catch it early. Sonnet 5 is the default for everything else. Haiku 4.5 only shows up twice, for the two genuinely mechanical, no-judgment chunks (state data table, test boilerplate).

Dropping Clerk also drops a paid vendor and its SDK surface area — Supabase Auth is included in the Supabase project you're already paying for.

## 6. What "Done" Looks Like (native-specific additions to the earlier checklist)

- [ ] Everything from the earlier Base44 "done" checklist still applies (consent flow, upload, letters, deadlines, account deletion, legal pages, no green in the palette).
- [ ] Confirmed via `strings` or a binary inspection that no secret (Anthropic key, service-role key) appears anywhere in the compiled app bundle.
- [ ] Tested on a physical iPhone, not just Simulator — permissions prompts (documents, notifications), Sign in with Apple, and StoreKit sandbox purchases all behave correctly.
- [ ] A scanned (image-only) lease PDF runs end-to-end through the OCR fallback and produces an analysis.
- [ ] Local notification fires for a test deadline; email reminder arrives via Resend.
- [ ] Memory/performance profiled with Instruments on at least one real lease upload + analysis cycle.
- [ ] Two real test accounts confirm RLS isolation end-to-end through the actual app — tables *and* Storage — not just at the database level.
- [ ] Account deletion verified to remove all 5 tables' rows, Storage objects, the RevenueCat subscriber, and the auth user.
- [ ] `PrivacyInfo.xcprivacy` present and complete; App Privacy labels drafted.
- [ ] App Review notes drafted and ready for submission.
