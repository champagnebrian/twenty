# LeaseOwl — Backend Architecture (Phase 0 output)

This is the Phase 0 deliverable from `docs/leaseowl/native-ios-handoff.md` (Rev. 2).
Everything the iOS client (built on the Mac Mini, Phases 1+) needs to integrate
against is specified here. The schema is in `../supabase/migrations/0001_init.sql`;
the Edge Functions are in `../supabase/functions/`.

> **RECONCILE-WITH-BASE44:** table field lists, the two system prompts, and any
> consent/legal copy referenced here were drafted fresh in this session because
> the Base44 originals were not available. Diff against the originals before
> launch. Nothing structural (RLS, contracts, deletion order) depends on them.

---

## 1. Trust model

- The iOS client holds only the Supabase **project URL** and **anon key** (public
  by design). Row Level Security is the data boundary: every table and the
  `leases` storage bucket enforce `user_id = auth.uid()`.
- The **Anthropic key**, **service-role key**, **Upstash credentials**,
  **RevenueCat secret**, and **Resend key** exist only as Edge Function secrets.
  No code path returns them to the client, and functions must never log request
  bodies (lease text) or secrets.
- The client is never trusted for: rate limits, the free-tier letter cap,
  Pro entitlement, or deletion. All four are enforced server-side.

## 2. PII tokenization (on-device, before any network call)

**Source of truth:** tenant name and property address are **structured user
input** (profile fields collected before first analysis) — never extracted from
the lease by NLP. Deterministic replacement is verifiable in Phase 11; entity
extraction is not.

**Client-side pipeline, in order, before every Claude-bound request:**

1. Replace every occurrence of the stored tenant name → `[TENANT]`
   (case-insensitive, plus a last-name-only pass when the surname is ≥ 4 chars).
2. Replace every occurrence of the stored property address → `[ADDRESS]`
   (normalize whitespace and common abbreviations — St/Street, Apt/Unit —
   before matching).
3. Regex scrub pass over the full text:
   - SSN (`\d{3}-\d{2}-\d{4}` and 9-digit runs in SSN-labeled context) → `[SSN]`
   - Phone numbers (NANP formats) → `[PHONE]`
   - Email addresses → `[EMAIL]`
4. Assert: the outgoing payload contains none of the stored PII strings.
   If the assertion fails, block the request and surface an error — never
   send anyway.

**Residual risk (documented, not solved):** co-tenant or landlord names the
user has not entered cannot be caught deterministically. Acceptable for v1;
the AI-transparency consent screen already discloses that lease text is
processed by Claude.

**Detokenization** (demand letters): the Edge Function returns and stores the
letter **with tokens in place** (`letters.body_tokenized`). The client
substitutes the real name/address locally for display, copy, and PDF export.
Real PII therefore never round-trips through the server or the Claude API.

## 3. Edge Function contracts

All functions: `POST`, `Authorization: Bearer <supabase access token>`
(verified with the anon-key client; the function derives `user_id` from the
JWT — the client never supplies a user id), JSON bodies, JSON responses.
Errors use `{ "error": { "code": string, "message": string } }` with proper
HTTP status. CORS is irrelevant for the native app but the shared handler
answers `OPTIONS` anyway so web-based testing works.

### 3.1 `analyze-lease`

Request:
```json
{ "document_id": "uuid", "state_code": "CA", "lease_text": "<TOKENIZED text>" }
```

Pipeline (order is load-bearing):
1. Verify JWT → `user_id`.
2. **Rate limit** (Upstash): `ratelimit:analyze:<user_id>`, 5 requests / hour
   fixed window → `429` with `retry_after_seconds` when exceeded.
3. Sanity guard: reject text > 150k chars (`413`) or < 200 chars (`422`).
4. Verify `document_id` belongs to `user_id`; set status `analyzing`.
5. Call Claude (`claude-opus-4-8`, structured output — see §4).
6. Insert `flags` rows (service role), set document status `analyzed`.
7. Return `{ "flags": [...] }` (same shape as the table rows).

On Claude failure: document status `failed`, `502` with a safe message
(never the raw provider error, which could echo prompt content).

### 3.2 `generate-letter`

Request:
```json
{ "letter_type": "deposit_return", "state_code": "CA",
  "document_id": "uuid | null", "details": "<TOKENIZED free-text input>" }
```

Pipeline:
1. Verify JWT → `user_id`.
2. Rate limit: `ratelimit:letter:<user_id>`, 5 / hour.
3. **Free-tier cap (server-side):** if the user is not Pro, count
   `letters` rows for this user in the current UTC calendar month; ≥ 3 → `402`
   `{ code: "letter_cap_reached" }`. Pro check = RevenueCat REST
   `GET /v1/subscribers/<user_id>` looking for an active `pro` entitlement
   (user_id is the RevenueCat app user id; set it to the Supabase uid in the
   client SDK at login).
4. Call Claude with the demand-letter system prompt.
5. Insert the `letters` row (tokenized body), return it.

### 3.3 `delete-account`

Request: empty body. Apple Guideline 5.1.1(v) — this must fully work.

Deletion order (auth record last, so a partial failure never strands data
behind a deleted login; every step idempotent so the client can retry):
1. Verify JWT → `user_id`.
2. Delete storage objects under `leases/<user_id>/` (list + remove, batched).
3. Delete RevenueCat subscriber (`DELETE /v1/subscribers/<user_id>`);
   404 is success. RevenueCat deletion does NOT cancel an active App Store
   subscription — the client must tell the user to cancel in Settings.
4. Delete the `public.users` row (service role) — `documents`, `flags`,
   `letters`, `deadlines` all cascade via FK.
5. `auth.admin.deleteUser(user_id)`.
6. Return `204`.

### 3.4 `send-reminders`

Invoked by `pg_cron` (daily, e.g. `0 14 * * *` UTC ≈ morning US time) via
`net.http_post` with the function's URL and a shared `CRON_SECRET` header —
**not** user-JWT authenticated. Reject any call without the secret.

Pipeline: select `deadlines` where `due_on` between today and today+7 and
`reminder_sent_at is null`, join emails from `auth.users`, send one Resend
email per deadline, set `reminder_sent_at`. Local notifications on-device are
the primary reminder channel (Phase 8); this email is the fallback.

## 4. Claude integration

- Model: `claude-opus-4-8`, called via the official `@anthropic-ai/sdk`
  (Deno `npm:` specifier), `max_tokens` 16000, non-streaming (Edge Function
  responses are single JSON documents; payloads are well under timeout risk).
- **Structured output** for the analyzer: `output_config.format` with a JSON
  schema (array of flags: severity enum / clause_quote / explanation /
  suggested_action) so parsing can't fail on prose drift.
- Handle `stop_reason === "refusal"` explicitly (return a safe 502-class
  error; never retry in a loop).
- System prompts live in `../prompts/` and are inlined into the functions at
  deploy time (they contain no secrets). The prompts:
  - never claim legal advice, guaranteed outcomes, or use the word "illegal"
    (use "may not comply with <STATE> law" / "potentially unenforceable");
  - instruct the model to preserve `[TENANT]`/`[ADDRESS]`/`[SSN]`/`[PHONE]`/
    `[EMAIL]` tokens verbatim and never invent replacements;
  - require the disclaimer line in every letter body.

## 5. Rate limiting (Upstash Redis, REST API)

Fixed window: key `ratelimit:<op>:<user_id>:<floor(now / windowSeconds)>`,
`INCR` + `EXPIRE windowSeconds` on first hit; over limit → 429. Fixed window
(vs sliding) is deliberate: both AI ops are low-frequency (5/hour), so
boundary bursts are a non-issue and the implementation stays ~20 lines.
**Fail closed** on Upstash errors for AI endpoints (a Redis outage must not
turn into an unmetered Claude bill).

## 6. Required Edge Function secrets

| Secret | Used by |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | all (JWT verification) — injected automatically |
| `SUPABASE_SERVICE_ROLE_KEY` | analyze-lease, generate-letter, delete-account, send-reminders — injected automatically |
| `ANTHROPIC_API_KEY` | analyze-lease, generate-letter |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | analyze-lease, generate-letter |
| `REVENUECAT_SECRET_KEY` | generate-letter, delete-account |
| `RESEND_API_KEY` | send-reminders |
| `CRON_SECRET` | send-reminders |

## 7. What the iOS client must implement against this

- Supabase Auth (Sign in with Apple + magic link) via `supabase-swift`;
  create the `users` profile row on first sign-in; set the RevenueCat app
  user id to the Supabase uid.
- Tokenization pipeline of §2 before calling `analyze-lease` /
  `generate-letter`; detokenization after `generate-letter`.
- Upload PDFs to `leases/<uid>/<document_id>.pdf`; PDFKit extraction with
  the Vision OCR fallback (handoff doc Phase 5).
- Local notifications for deadlines (handoff doc Phase 8).
- Call `delete-account` from Settings and then sign out locally.
