"""REST API endpoints exposing TenUp tournaments."""
from __future__ import annotations

import sqlite3
from typing import Optional

from flask import Blueprint, jsonify, request

from services.db_import import ensure_schema, fetch_all_tournaments
from tenpadel.config_paths import DB_PATH

bp = Blueprint("tournaments", __name__)


def _parse_limit(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, limit)


@bp.route("/api/tournaments")
def list_tournaments():
    limit = _parse_limit(request.args.get("limit"))
    items = fetch_all_tournaments(limit=limit)
    return jsonify(items)


@bp.route("/api/_count")
def count():
    ensure_schema()
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM tournaments")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tournaments WHERE COALESCE(start_date,'')!=''")
    dated = cur.fetchone()[0]
    con.close()
    return jsonify({"db": str(DB_PATH), "total": total, "with_start_date": dated})
