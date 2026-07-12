-- LeaseOwl — initial schema (Phase 0 output, Rev. 2 handoff)
--
-- RECONCILE-WITH-BASE44: field lists below were drafted fresh because the
-- Base44 schema doc was not available to this session. Before launch, diff
-- each table against the original spec and adjust columns — the RLS policies,
-- triggers, and bucket setup do not depend on the exact column list.
--
-- Security model: every table carries RLS with `user_id = auth.uid()`.
-- Supabase Auth issues the JWTs, so auth.uid() works as written (this is
-- why the stack switched from Clerk — see docs/leaseowl/native-ios-handoff.md).

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

create table public.users (
  id uuid primary key references auth.users (id) on delete cascade,
  state_code text check (state_code in ('CA', 'NY', 'TX', 'FL', 'IL', 'NV')),
  -- Structured PII used for on-device tokenization. Stored so the client can
  -- prefill; NEVER sent to an Edge Function or the Claude API.
  tenant_full_name text,
  property_address text,
  consented_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  title text not null default 'Untitled lease',
  -- Path of the original PDF inside the 'leases' storage bucket
  -- (format: <user_id>/<document_id>.pdf), null for paste-text documents.
  storage_path text,
  -- Extraction provenance matters for debugging analysis quality.
  source text not null default 'pdf' check (source in ('pdf', 'ocr', 'paste')),
  extracted_text text,
  status text not null default 'uploaded'
    check (status in ('uploaded', 'analyzing', 'analyzed', 'failed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.flags (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  document_id uuid not null references public.documents (id) on delete cascade,
  severity text not null check (severity in ('high', 'medium', 'low')),
  clause_quote text not null,
  explanation text not null,
  suggested_action text not null,
  created_at timestamptz not null default now()
);

create table public.letters (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  document_id uuid references public.documents (id) on delete set null,
  letter_type text not null
    check (letter_type in ('deposit_return', 'repair_request', 'quiet_enjoyment', 'lease_termination', 'other')),
  -- Stored WITH tokens ([TENANT]/[ADDRESS]/...); detokenization is on-device only.
  body_tokenized text not null,
  created_at timestamptz not null default now()
);

create table public.deadlines (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  kind text not null default 'deposit_return',
  label text not null,
  due_on date not null,
  state_code text not null,
  reminder_sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Indexes (every RLS predicate and lookup path)
-- ---------------------------------------------------------------------------

create index documents_user_id_idx on public.documents (user_id);
create index flags_user_id_idx on public.flags (user_id);
create index flags_document_id_idx on public.flags (document_id);
create index letters_user_id_idx on public.letters (user_id);
-- Server-side free-tier cap: count letters per user per calendar month.
create index letters_user_created_idx on public.letters (user_id, created_at);
create index deadlines_user_id_idx on public.deadlines (user_id);
-- Reminder cron scans by due date for unsent reminders.
create index deadlines_due_unsent_idx on public.deadlines (due_on)
  where reminder_sent_at is null;

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------

create function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger users_set_updated_at
  before update on public.users
  for each row execute function public.set_updated_at();

create trigger documents_set_updated_at
  before update on public.documents
  for each row execute function public.set_updated_at();

create trigger deadlines_set_updated_at
  before update on public.deadlines
  for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Row Level Security — user_id = auth.uid(), no exceptions
-- ---------------------------------------------------------------------------

alter table public.users enable row level security;
alter table public.documents enable row level security;
alter table public.flags enable row level security;
alter table public.letters enable row level security;
alter table public.deadlines enable row level security;

-- users: the row id IS the auth uid.
create policy users_select on public.users
  for select using (id = auth.uid());
create policy users_insert on public.users
  for insert with check (id = auth.uid());
create policy users_update on public.users
  for update using (id = auth.uid()) with check (id = auth.uid());
-- No user-facing delete policy: account deletion goes through the
-- delete-account Edge Function (service role), which bypasses RLS.

create policy documents_select on public.documents
  for select using (user_id = auth.uid());
create policy documents_insert on public.documents
  for insert with check (user_id = auth.uid());
create policy documents_update on public.documents
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy documents_delete on public.documents
  for delete using (user_id = auth.uid());

-- flags are written by the analyze-lease Edge Function (service role) and
-- read by the client; users may delete flags (e.g. dismissing) but not
-- insert or edit them.
create policy flags_select on public.flags
  for select using (user_id = auth.uid());
create policy flags_delete on public.flags
  for delete using (user_id = auth.uid());

-- letters are written by the generate-letter Edge Function (service role,
-- which also enforces the free-tier cap); client reads and deletes.
create policy letters_select on public.letters
  for select using (user_id = auth.uid());
create policy letters_delete on public.letters
  for delete using (user_id = auth.uid());

create policy deadlines_select on public.deadlines
  for select using (user_id = auth.uid());
create policy deadlines_insert on public.deadlines
  for insert with check (user_id = auth.uid());
create policy deadlines_update on public.deadlines
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy deadlines_delete on public.deadlines
  for delete using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Storage: private 'leases' bucket, per-user folder isolation
-- Object paths are '<user_id>/<document_id>.pdf'; the first path segment
-- must equal the caller's uid.
-- ---------------------------------------------------------------------------

insert into storage.buckets (id, name, public)
values ('leases', 'leases', false);

create policy leases_select on storage.objects
  for select using (
    bucket_id = 'leases'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy leases_insert on storage.objects
  for insert with check (
    bucket_id = 'leases'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy leases_delete on storage.objects
  for delete using (
    bucket_id = 'leases'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
