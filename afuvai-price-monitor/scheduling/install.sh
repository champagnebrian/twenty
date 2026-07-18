#!/bin/bash
# One-time install of the weekly price-monitor job on the Nova / Mac Mini
# stack. Run from anywhere: bash scheduling/install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLIST_SRC="$REPO_DIR/afuvai-price-monitor/scheduling/com.afuvai.price-monitor.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.afuvai.price-monitor.plist"

command -v claude >/dev/null || {
    echo "ERROR: claude CLI not found. Install Claude Code first (or edit the"
    echo "plist to pass 'local' instead of 'agent' for connector-free mode)."
    exit 1
}

mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$PLIST_SRC" > "$PLIST_DST"
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
echo "Installed: weekly run Mondays 07:00 local. Logs: /tmp/afuvai-price-monitor.log"
echo "IMPORTANT: once this is confirmed working, disable the interim cloud"
echo "Routine (see afuvai-price-monitor/README.md 'Scheduling ownership')."
