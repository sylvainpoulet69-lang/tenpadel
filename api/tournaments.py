"""REST API endpoints exposing TenUp tournaments."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
import sqlite3

from tenpadel.config_paths import DB_PATH

bp = Blueprint("tournaments", __name__)


def _fetch_all(limit: int = 1000):
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, category, level, club_name, city,
               start_date, end_date, detail_url, registration_url
        FROM tournaments
        ORDER BY (start_date IS NULL), start_date ASC, id DESC
        LIMIT ?
    """,
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    for r in rows:
        r["date"] = r.get("start_date")
    return rows


@bp.route("/api/tournaments")
def list_tournaments():
    limit = int(request.args.get("limit", 1000))
    return jsonify(_fetch_all(limit))


@bp.route("/api/_count")
def count():
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM tournaments")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tournaments WHERE COALESCE(start_date,'')!=''")
    dated = cur.fetchone()[0]
    con.close()
    return jsonify({"db": str(DB_PATH), "total": total, "with_start_date": dated})
