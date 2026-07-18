#!/bin/bash
# Weekly AFUVAI price-monitor run. Two modes:
#   agent (default) — drives a headless Claude Code session that follows
#     agents/weekly-digest-agent.md end to end (Gmail sweep, sheet merge,
#     analysis, digest publish). Requires `claude` CLI with the Gmail +
#     Google Drive connectors authorized.
#   local — no network/connectors: merges any manually downloaded Quick
#     Entry export sitting in data/inbox/, runs the analysis, writes the
#     digest to reports/, commits. Use when the agent path is unavailable.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-agent}"
cd "$REPO_DIR"

git pull --ff-only || echo "WARN: git pull failed; running on local state"

if [ "$MODE" = "agent" ]; then
    claude -p "You are running the scheduled weekly job for the AFUVAI vendor price monitor. Working directory: $REPO_DIR. Follow agents/ingestion-agent.md (email sweep) and then agents/weekly-digest-agent.md (merge, analysis, digest, publish) exactly. Respect every prohibition in those runbooks." \
        --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
        --permission-mode acceptEdits
else
    shopt -s nullglob
    for export_file in data/inbox/*.csv data/inbox/*.xlsx; do
        (cd src && python3 -m pricemonitor merge-sheet "../$export_file")
        mv "$export_file" "$export_file.processed"
    done
    (cd src && python3 -m pricemonitor expire-proposals)
    (cd src && python3 -m pricemonitor weekly-digest --output "../reports/digest-$(date +%F).md")
fi

git add -A data reports
git commit -m "weekly run $(date +%F) [$MODE mode]" || echo "nothing to commit"
git push || echo "WARN: push failed; digest is committed locally"
