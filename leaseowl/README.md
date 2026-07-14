# LeaseOwl — Backend (Phase 0 + server side)

This directory is the executed backend slice of `docs/leaseowl/native-ios-handoff.md`
(Rev. 2). It was produced in a Linux Claude Code session; the iOS client
(Phases 1+) is built separately on the Mac Mini and integrates against the
contracts in `docs/architecture.md`.

## Layout

```
docs/architecture.md          Phase 0 architecture: trust model, tokenization,
                              Edge Function contracts, deletion order, secrets
prompts/                      The two system prompts (drafted fresh —
                              RECONCILE-WITH-BASE44 before launch)
supabase/migrations/          0001_init.sql — 5 tables, RLS, storage bucket
supabase/functions/           analyze-lease, generate-letter, delete-account,
                              send-reminders (+ _shared helpers)
```

## Deploying to a real Supabase project (Mac Mini session)

```sh
supabase init            # once, in the fresh app repo (copy this dir in)
supabase link --project-ref <ref>
supabase db push         # applies migrations/0001_init.sql

supabase secrets set \
  ANTHROPIC_API_KEY=... \
  UPSTASH_REDIS_REST_URL=... \
  UPSTASH_REDIS_REST_TOKEN=... \
  REVENUECAT_SECRET_KEY=... \
  RESEND_API_KEY=... \
  CRON_SECRET=...

supabase functions deploy analyze-lease generate-letter delete-account send-reminders
```

Then schedule the reminder cron (SQL editor, once — see the comment block at
the top of `supabase/functions/send-reminders/index.ts` for the exact
`cron.schedule` + `net.http_post` statement; requires the `pg_cron` and
`pg_net` extensions enabled in the dashboard).

## Verification status (from the Linux session)

- `0001_init.sql` was applied to a scratch Postgres with a stubbed `auth`/
  `storage` schema and passed a two-user RLS isolation smoke test (see the
  session log / commit message for details).
- Edge Function TypeScript was type-checked with `deno check`.
- No live Supabase project was provisioned; `db push` / `functions deploy`
  and end-to-end calls happen on the Mac Mini.

## Invariants the client must respect (see docs/architecture.md)

- Only tokenized text is ever sent to `analyze-lease` / `generate-letter`.
- Detokenization of letters is on-device only.
- Storage object paths are `leases/<auth uid>/<document_id>.pdf`.
- The RevenueCat app user id is the Supabase auth uid.
