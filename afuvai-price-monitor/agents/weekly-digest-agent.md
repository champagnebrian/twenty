# Weekly Digest Agent Runbook — merge, analyze, publish

The scheduled weekly job (interim: cloud Routine; target: Mac Mini launchd —
see scheduling/). Runs AFTER the ingestion sweep in
`agents/ingestion-agent.md`. Repo root for all paths: `afuvai-price-monitor/`.
All prohibitions from the ingestion runbook apply here too (read-only Gmail;
Drive writes = new files only; never touch the Expense Tracker).

## Procedure

1. **Ingestion sweep** — follow `agents/ingestion-agent.md` end to end
   (scoped Gmail search → proposals). Skip only if it already ran today.
2. **Pull the entry sheet** — download the Quick Entry Google Sheet
   (`config/drive.json` → quick_entry_sheet.file_id) via the Drive
   connector's read tool, save the rows below the header
   (marker `date,vendor_id,stem_id`) as a CSV under `data/inbox/`.
3. **Merge** — `cd src && python3 -m pricemonitor merge-sheet
   ../data/inbox/<file>.csv` (dedupes; flips matching proposals to
   confirmed; expires stale ones). Delete or archive the inbox file after.
4. **Analyze + digest** — `python3 -m pricemonitor weekly-digest`
   → writes `reports/digest-<date>.md`.
5. **Snapshot on breach** — if the digest shows any tier ALERT, run the
   snapshot (the analysis pipeline appends to `data/tier-price-history.csv`
   with the trigger); confirm the row landed.
6. **Publish**:
   - Commit + push: `data/`, `reports/` (message: `weekly run <date>`).
   - Create a NEW Drive file in the Afuvai folder named
     `AFUVAI Price Digest <date>` from the digest markdown text (text
     upload → becomes a Google Doc). Never overwrite a previous digest.
   - Create a Gmail DRAFT to altmannbrian@gmail.com, subject
     `AFUVAI price digest <date>`, body = the digest markdown. Draft only —
     never send.
7. **Surface** — end the session with a concise summary of the digest's
   "Needs attention" line; the Routine's completion notification (email +
   push) carries it to Brian. If the week is quiet, the notification says so
   in one line — no noise beyond that.

## Failure handling

- Sheet unreachable → run steps 4–7 from the existing price log; note the
  skipped merge in the digest header.
- A merge row fails validation → leave it out, list it in the digest under
  "Needs attention" with the exact error (Brian fixes the cell); never
  guess a correction.
- Push fails → still create the Drive digest file and finish; note the
  unpushed commit in the summary.
