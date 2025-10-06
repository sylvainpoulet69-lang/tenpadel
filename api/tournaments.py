"""REST API endpoints exposing TenUp tournaments."""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import asc, desc

from services.tournament_store_models import TournamentRecord

bp = Blueprint("tournaments_api", __name__, url_prefix="/api")


@bp.route("/tournaments", methods=["GET"])
def list_tournaments():
    """Return all tournaments ordered by their start date."""

    limit_raw = request.args.get("limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else 1000
    except (TypeError, ValueError):
        limit = 1000
    limit = max(1, min(limit, 5000))

    query = TournamentRecord.query.order_by(
        TournamentRecord.start_date.is_(None),
        asc(TournamentRecord.start_date),
        desc(TournamentRecord.id),
    )

    rows = query.limit(limit).all()
    return jsonify([row.to_dict() for row in rows])
