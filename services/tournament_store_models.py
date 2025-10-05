"""Database models used to persist TenUp tournaments."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import pendulum

from extensions import db
from models.tournament import Tournament


class TournamentRecord(db.Model):
    __tablename__ = "tournaments"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(32), nullable=False, index=True)
    external_id = db.Column(db.String(128), nullable=False, index=True)
    title = db.Column(db.String(512), nullable=False)
    discipline = db.Column(db.String(32), nullable=False)
    category = db.Column(db.String(16), nullable=False, index=True)
    level = db.Column(db.String(32))
    start_date = db.Column(db.String(10), nullable=False, index=True)
    end_date = db.Column(db.String(10), nullable=False)
    city = db.Column(db.String(128))
    postal_code = db.Column(db.String(32))
    region = db.Column(db.String(128), index=True)
    club_name = db.Column(db.String(256))
    price = db.Column(db.Float)
    registration_url = db.Column(db.String(512), nullable=False)
    details_url = db.Column(db.String(512), nullable=False)
    inscriptions_open = db.Column(db.Boolean)
    slots_total = db.Column(db.Integer)
    slots_taken = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint(
            "source", "external_id", "start_date", name="uq_tournaments_source_external_start"
        ),
    )

    @classmethod
    def from_model(cls, model: Tournament) -> "TournamentRecord":
        created_at = pendulum.parse(model.created_at, strict=False).naive()
        instance = cls(
            source=model.source,
            external_id=model.external_id,
            title=model.title,
            discipline=model.discipline,
            category=model.category,
            level=model.level,
            start_date=model.start_date,
            end_date=model.end_date,
            city=model.city,
            postal_code=model.postal_code,
            region=model.region,
            club_name=model.club_name,
            price=model.price,
            registration_url=str(model.registration_url),
            details_url=str(model.details_url),
            inscriptions_open=model.inscriptions_open,
            slots_total=model.slots_total,
            slots_taken=model.slots_taken,
            created_at=created_at,
            updated_at=created_at,
        )
        return instance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "title": self.title,
            "discipline": self.discipline,
            "category": self.category,
            "level": self.level,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "city": self.city,
            "postal_code": self.postal_code,
            "region": self.region,
            "club_name": self.club_name,
            "price": self.price,
            "registration_url": self.registration_url,
            "details_url": self.details_url,
            "inscriptions_open": self.inscriptions_open,
            "slots_total": self.slots_total,
            "slots_taken": self.slots_taken,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
