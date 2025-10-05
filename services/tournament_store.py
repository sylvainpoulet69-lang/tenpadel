"""Persistent storage utilities for TenUp tournaments."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import json

from flask_sqlalchemy import SQLAlchemy

from models.tournament import Tournament


def ensure_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    def as_dict(self) -> dict:
        return {"inserted": self.inserted, "updated": self.updated, "skipped": self.skipped}


class TournamentStore:
    """Service responsible for persisting tournaments to the database and JSON."""

    def __init__(self, db: SQLAlchemy, json_path: Path) -> None:
        self._db = db
        self._json_path = json_path
        ensure_directory(self._json_path)

    def upsert_many(self, records: Iterable[Tournament]) -> UpsertResult:
        from services.tournament_store_models import TournamentRecord  # circular

        session = self._db.session
        stats = UpsertResult()
        now = datetime.utcnow()

        for entry in records:
            key = {
                "source": entry.source,
                "external_id": entry.external_id,
                "start_date": entry.start_date,
            }
            existing = session.query(TournamentRecord).filter_by(**key).one_or_none()
            if existing is None:
                instance = TournamentRecord.from_model(entry)
                instance.created_at = now
                instance.updated_at = now
                session.add(instance)
                stats.inserted += 1
                continue

            payload = entry.model_dump(exclude={"source"})
            changed = False
            for field, value in payload.items():
                if getattr(existing, field) != value:
                    setattr(existing, field, value)
                    changed = True
            if changed:
                existing.updated_at = now
                stats.updated += 1
            else:
                stats.skipped += 1

        session.commit()
        self._export_json()
        return stats

    def _export_json(self) -> None:
        from services.tournament_store_models import TournamentRecord  # circular

        session = self._db.session
        rows: List[TournamentRecord] = (
            session.query(TournamentRecord).order_by(TournamentRecord.start_date.asc()).all()
        )
        payload = {
            "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
            "source": "tenup",
            "tournaments": [row.to_dict() for row in rows],
        }
        ensure_directory(self._json_path)
        self._json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


