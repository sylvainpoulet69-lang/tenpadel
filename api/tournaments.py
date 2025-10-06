"""REST API endpoints exposing TenUp tournaments."""
from __future__ import annotations

from typing import List, Sequence

import pendulum
from flask import Blueprint, jsonify, request
from sqlalchemy import asc, desc, or_

from services.tournament_store_models import TournamentRecord

bp = Blueprint("tournaments_api", __name__, url_prefix="/api")


def _parse_levels(raw_level: str | Sequence[str] | None) -> List[str]:
    if raw_level is None:
        return []
    if isinstance(raw_level, (list, tuple)):
        return [str(item).upper() for item in raw_level if item]
    return [token.strip().upper() for token in str(raw_level).split(",") if token.strip()]


@bp.route("/tournaments", methods=["GET"])
def list_tournaments():
    limit_raw = request.args.get("limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else 1000
    except (TypeError, ValueError):
        limit = 1000
    limit = max(1, min(limit, 5000))

    query = TournamentRecord.query
    category = request.args.get("category")
    if category:
        query = query.filter(TournamentRecord.category == category.upper())

    level_tokens = _parse_levels(request.args.getlist("level"))
    if level_tokens:
        query = query.filter(TournamentRecord.level.in_(level_tokens))

    city = request.args.get("city")
    if city:
        city = city.strip()
        if city:
            query = query.filter(
                or_(
                    TournamentRecord.city.ilike(f"%{city}%"),
                    TournamentRecord.city.is_(None),
                    TournamentRecord.city == "",
                )
            )

    region = request.args.get("region")
    if region:
        region = region.strip()
        if region:
            query = query.filter(
                or_(
                    TournamentRecord.region == region,
                    TournamentRecord.region.is_(None),
                    TournamentRecord.region == "",
                )
            )

    date_from = request.args.get("from")
    date_to = request.args.get("to")
    start = None
    end = None
    if date_from:
        try:
            start = pendulum.parse(date_from, strict=False).to_date_string()
        except Exception:  # pragma: no cover - invalid user input
            start = None
    if date_to:
        try:
            end = pendulum.parse(date_to, strict=False).to_date_string()
        except Exception:  # pragma: no cover - invalid user input
            end = None

    if start and end:
        query = query.filter(
            or_(
                TournamentRecord.start_date.between(start, end),
                TournamentRecord.start_date.is_(None),
                TournamentRecord.start_date == "",
            )
        )
    elif start:
        query = query.filter(
            or_(
                TournamentRecord.start_date >= start,
                TournamentRecord.start_date.is_(None),
                TournamentRecord.start_date == "",
            )
        )
    elif end:
        query = query.filter(
            or_(
                TournamentRecord.start_date <= end,
                TournamentRecord.start_date.is_(None),
                TournamentRecord.start_date == "",
            )
        )

    query = query.order_by(
        TournamentRecord.start_date.is_(None),
        asc(TournamentRecord.start_date),
        desc(TournamentRecord.id),
    )

    rows = query.limit(limit).all()
    return jsonify([row.to_dict() for row in rows])
