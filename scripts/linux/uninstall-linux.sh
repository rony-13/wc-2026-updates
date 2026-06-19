#!/usr/bin/env bash
# Stop the dashboard and remove it from login startup on Linux.
set -euo pipefail

DEST="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/worldcup-dashboard.desktop"

if [ -f "$DEST" ]; then
  rm -f "$DEST"
  echo "==> Removed $DEST — the dashboard will no longer start at login."
else
  echo "==> Nothing to remove (autostart entry not found)."
fi

# Best-effort: stop any running instance.
pkill -f "run.py" 2>/dev/null || true
echo "==> Done."
