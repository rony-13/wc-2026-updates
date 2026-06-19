#!/usr/bin/env bash
# Install the World Cup 2026 dashboard as a macOS LaunchAgent so it starts at
# login and stays running. Re-running this is safe (it reloads the agent).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LABEL="com.worldcup.dashboard"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
TEMPLATE="$REPO_DIR/scripts/macos/${LABEL}.plist.template"

echo "==> Repo: $REPO_DIR"

# 1. Virtual environment + dependencies
if [ ! -d "$REPO_DIR/.venv" ]; then
  echo "==> Creating virtual environment"
  python3 -m venv "$REPO_DIR/.venv"
fi
"$REPO_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REPO_DIR/.venv/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
PYTHON="$REPO_DIR/.venv/bin/python"
echo "==> Dependencies installed"

# 2. .env scaffold (never overwrite an existing one)
if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  echo "==> Created .env (edit it to add a football-data.org key for faster live updates)"
fi

# 3. Render and install the LaunchAgent
mkdir -p "$HOME/Library/LaunchAgents" "$REPO_DIR/data/cache"
sed -e "s|__PYTHON__|$PYTHON|g" -e "s|__WORKDIR__|$REPO_DIR|g" \
  "$TEMPLATE" > "$PLIST_DST"
echo "==> Wrote $PLIST_DST"

# 4. (Re)load it
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
echo "==> LaunchAgent loaded — the dashboard now starts at every login."

PORT="$(grep -E '^PORT=' "$REPO_DIR/.env" | cut -d= -f2 || true)"
PORT="${PORT:-8765}"
echo ""
echo "Dashboard will be available at: http://127.0.0.1:${PORT}/"
echo "It is starting now and your browser should open shortly."
echo "To stop it from running at login: scripts/macos/uninstall-macos.sh"
