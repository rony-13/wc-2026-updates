"""HTTP layer: one HTML page plus two JSON endpoints the page polls."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, current_app

bp = Blueprint("main", __name__)


def _service():
    return current_app.config["WC_SERVICE"]


@bp.route("/")
def index():
    cfg = current_app.config
    return render_template(
        "index.html",
        today_interval=30,
        groups_interval=60,
        refresh_seconds=cfg["WC_CONFIG"].REFRESH_SECONDS,
    )


@bp.route("/api/today")
def api_today():
    return jsonify(_service().get_today())


@bp.route("/api/groups")
def api_groups():
    return jsonify(_service().get_groups())


@bp.route("/api/health")
def api_health():
    svc = _service()
    return jsonify({"ok": True, "source": svc._source, "updated_at": svc._updated_at})
