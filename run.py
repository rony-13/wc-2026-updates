#!/usr/bin/env python3
"""Run the World Cup 2026 dashboard.

    python run.py

Starts the local server, kicks off the background refresh loop, and (unless
NO_BROWSER=1) opens the dashboard in your default browser. Designed to be
launched at login by the macOS LaunchAgent in scripts/.
"""
from __future__ import annotations

import os
import threading
import webbrowser

from app import create_app
from app.config import Config


def _open_browser(url: str) -> None:
    if os.environ.get("NO_BROWSER") == "1":
        return
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()


def main() -> None:
    config = Config()
    app = create_app(config)
    url = f"http://{config.HOST}:{config.PORT}/"
    _open_browser(url)
    print(f"World Cup 2026 dashboard running at {url}")
    # threaded so the 30s/60s frontend polls never queue behind each other;
    # use_reloader=False so the background scheduler isn't started twice.
    app.run(host=config.HOST, port=config.PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
