#!/usr/bin/env bash
# Stop the dashboard and remove it from login startup.
set -euo pipefail

LABEL="com.worldcup.dashboard"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [ -f "$PLIST_DST" ]; then
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  rm -f "$PLIST_DST"
  echo "==> Removed $PLIST_DST — the dashboard will no longer start at login."
else
  echo "==> Nothing to remove (LaunchAgent not installed)."
fi

# Best-effort: stop any running instance.
pkill -f "run.py" 2>/dev/null || true
echo "==> Done."
