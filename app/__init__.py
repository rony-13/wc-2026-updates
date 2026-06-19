"""Application factory: wire config, service, background refresh, and routes."""
from __future__ import annotations

import atexit

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

from .config import Config
from .preferences import PreferencesStore
from .routes import bp
from .service import WorldCupService


def create_app(config: Config | None = None, start_scheduler: bool = True) -> Flask:
    config = config or Config()
    app = Flask(__name__)

    service = WorldCupService(config)
    app.config["WC_SERVICE"] = service
    app.config["WC_CONFIG"] = config
    app.config["WC_PREFS"] = PreferencesStore(config.CACHE_DIR)
    app.register_blueprint(bp)

    # Prime data once at startup so the first request is never empty.
    service.refresh()

    if start_scheduler:
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            service.refresh,
            "interval",
            seconds=config.REFRESH_SECONDS,
            id="refresh",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        app.config["WC_SCHEDULER"] = scheduler
        atexit.register(lambda: scheduler.shutdown(wait=False))

    return app
