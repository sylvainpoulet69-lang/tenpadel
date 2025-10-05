"""SQLAlchemy models used to persist scraped tournaments."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from extensions import db


class TournamentRecord(db.Model):
    __tablename__ = "tournaments"

    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.String(128), unique=True, nullable=False, index=True)
    name = db.Column(db.String(512), nullable=False)
    level = db.Column(db.String(16))
    category = db.Column(db.String(16), nullable=False, index=True)
    club_name = db.Column(db.String(256))
    club_code = db.Column(db.String(64))
    organizer = db.Column(db.String(256))
    city = db.Column(db.String(128), index=True)
    region = db.Column(db.String(128), index=True)
    address = db.Column(db.String(512))
    start_date = db.Column(db.String(10), nullable=False, index=True)
    end_date = db.Column(db.String(10), nullable=False)
    registration_deadline = db.Column(db.String(10))
    surface = db.Column(db.String(64))
    indoor_outdoor = db.Column(db.String(64))
    draw_size = db.Column(db.Integer)
    price = db.Column(db.Float)
    status = db.Column(db.String(64))
    detail_url = db.Column(db.String(512), nullable=False)
    registration_url = db.Column(db.String(512))
    last_scraped_at = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def update_from_payload(self, payload: Dict[str, Any]) -> bool:
        changed = False
        for field, value in payload.items():
            if field in {"id", "created_at", "updated_at"}:
                continue
            if getattr(self, field) != value:
                setattr(self, field, value)
                changed = True
        return changed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tournament_id": self.tournament_id,
            "name": self.name,
            "title": self.name,
            "level": self.level,
            "category": self.category,
            "club_name": self.club_name,
            "club_code": self.club_code,
            "organizer": self.organizer,
            "city": self.city,
            "address": self.address,
            "region": self.region,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "registration_deadline": self.registration_deadline,
            "surface": self.surface,
            "indoor_outdoor": self.indoor_outdoor,
            "draw_size": self.draw_size,
            "price": self.price,
            "status": self.status,
            "detail_url": self.detail_url,
            "details_url": self.detail_url,
            "registration_url": self.registration_url,
            "last_scraped_at": self.last_scraped_at,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


__all__ = ["TournamentRecord"]

