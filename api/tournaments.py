"""REST API endpoints exposing TenUp tournaments."""
from __future__ import annotations

from typing import List, Sequence

import pendulum
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import asc, desc

from services.tournament_store_models import TournamentRecord

bp = Blueprint("tournaments_api", __name__, url_prefix="/api")


SORT_MAPPING = {
    "DATE_ASC": asc(TournamentRecord.start_date),
    "DATE_DESC": desc(TournamentRecord.start_date),
}


def _parse_levels(raw_level: str | Sequence[str] | None) -> List[str]:
    if raw_level is None:
        return []
    if isinstance(raw_level, (list, tuple)):
        return [str(item).upper() for item in raw_level if item]
    return [token.strip().upper() for token in str(raw_level).split(",") if token.strip()]


@bp.route("/tournaments", methods=["GET"])
def list_tournaments():
    query = TournamentRecord.query
    category = request.args.get("category")
    if category:
        query = query.filter(TournamentRecord.category == category.upper())

    level_tokens = _parse_levels(request.args.getlist("level"))
    if level_tokens:
        query = query.filter(TournamentRecord.level.in_(level_tokens))

    city = request.args.get("city")
    if city:
        query = query.filter(TournamentRecord.city.ilike(f"%{city}%"))

    region = request.args.get("region")
    if region:
        query = query.filter(TournamentRecord.region == region)

    date_from = request.args.get("from")
    if date_from:
        try:
            start = pendulum.parse(date_from, strict=False).to_date_string()
        except Exception:  # pragma: no cover - invalid user input
            start = None
        if start:
            query = query.filter(TournamentRecord.start_date >= start)

    date_to = request.args.get("to")
    if date_to:
        try:
            end = pendulum.parse(date_to, strict=False).to_date_string()
        except Exception:  # pragma: no cover - invalid user input
            end = None
        if end:
            query = query.filter(TournamentRecord.start_date <= end)

    sort = request.args.get("sort", "DATE_ASC").upper()
    order_clause = SORT_MAPPING.get(sort, SORT_MAPPING["DATE_ASC"])
    query = query.order_by(order_clause)

    page = max(int(request.args.get("page", 1)), 1)
    per_page_default = 50
    tenup_config = current_app.config.get("TENUP_CONFIG", {})
    per_page = int(request.args.get("limit", tenup_config.get("max_results", per_page_default)))
    per_page = max(1, min(per_page, int(tenup_config.get("max_results", 500))))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    items = [row.to_dict() for row in pagination.items]
    payload = {
        "page": page,
        "per_page": per_page,
        "total": pagination.total,
        "items": items,
    }
    return jsonify(payload)
