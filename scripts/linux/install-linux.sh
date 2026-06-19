#!/usr/bin/env bash
# Install the World Cup 2026 dashboard to start at login on Linux desktops
# (GNOME / KDE / XFCE / Cinnamon / ...) via a standard XDG autostart entry.
# Re-running is safe (it overwrites the entry).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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
  echo "==> Created .env (add a football-data.org key for faster live updates)"
fi
mkdir -p "$REPO_DIR/data/cache"

# 3. Render the XDG autostart entry
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
mkdir -p "$AUTOSTART_DIR"
DEST="$AUTOSTART_DIR/worldcup-dashboard.desktop"
sed -e "s|__PYTHON__|$PYTHON|g" -e "s|__WORKDIR__|$REPO_DIR|g" \
  "$REPO_DIR/scripts/linux/worldcup-dashboard.desktop.template" > "$DEST"
chmod +x "$DEST" 2>/dev/null || true
echo "==> Autostart entry written: $DEST"

# 4. Start it now
( cd "$REPO_DIR" && nohup "$PYTHON" run.py >/dev/null 2>&1 & )
echo "==> Dashboard starting…"

PORT="$(grep -E '^PORT=' "$REPO_DIR/.env" | cut -d= -f2 || true)"
PORT="${PORT:-8765}"
echo ""
echo "Dashboard will be available at: http://127.0.0.1:${PORT}/"
echo "It is starting now and your browser should open shortly."
echo "To stop it from running at login: scripts/linux/uninstall-linux.sh"
