"""HTTP layer: one HTML page plus two JSON endpoints the page polls."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, current_app, request

bp = Blueprint("main", __name__)


def _service():
    return current_app.config["WC_SERVICE"]


def _prefs():
    return current_app.config["WC_PREFS"]


@bp.route("/")
def index():
    cfg = current_app.config
    return render_template(
        "index.html",
        today_interval=30,
        groups_interval=60,
        refresh_seconds=cfg["WC_CONFIG"].REFRESH_SECONDS,
        read_only=cfg["WC_CONFIG"].PUBLIC_READONLY,
    )


@bp.route("/api/today")
def api_today():
    return jsonify(_service().get_today())


@bp.route("/api/groups")
def api_groups():
    return jsonify(_service().get_groups())


@bp.route("/api/knockout/round-of-32")
def api_round_of_32():
    return jsonify(_service().get_round_of_32())


@bp.route("/api/knockout/bracket")
def api_knockout_bracket():
    return jsonify(_service().get_knockout_bracket())


@bp.route("/api/teams")
def api_teams():
    return jsonify({"teams": _service().get_teams()})


@bp.route("/api/preferences", methods=["GET", "PUT"])
def api_preferences():
    store = _prefs()
    if request.method == "GET":
        return jsonify(store.load())
    if current_app.config["WC_CONFIG"].PUBLIC_READONLY:
        # Public deployment: favorite/following are set by the host editing
        # data/cache/preferences.json directly -- visitors can view but not change.
        return jsonify({"error": "preferences are managed by the host on this deployment"}), 403
    body = request.get_json(silent=True) or {}
    saved = store.save(body.get("favorite"), body.get("following") or [])
    return jsonify(saved)


@bp.route("/api/health")
def api_health():
    svc = _service()
    return jsonify({
        "ok": True,
        "source": svc._source,
        "updated_at": svc._updated_at,
        "providers": [p.name for p in svc.providers],
        "provider_errors": getattr(svc, "_provider_errors", {}),
    })
