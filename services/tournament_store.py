"""Helpers to persist scraped tournaments to JSON and SQLite."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from flask_sqlalchemy import SQLAlchemy

from services.tournament_store_models import TournamentRecord


def _ensure_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    def as_dict(self) -> dict:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
        }


class TournamentStore:
    """Persist tournaments to SQLite and JSON outputs."""

    def __init__(self, db: SQLAlchemy, json_path: Path) -> None:
        self._db = db
        self._json_path = json_path
        _ensure_directory(self._json_path)

    def upsert_many(self, records: Iterable[Mapping[str, object]]) -> UpsertResult:
        session = self._db.session
        stats = UpsertResult()
        now = datetime.utcnow()

        for payload in records:
            data = dict(payload)
            tournament_id = str(data["tournament_id"])
            existing = (
                session.query(TournamentRecord)
                .filter(TournamentRecord.tournament_id == tournament_id)
                .one_or_none()
            )
            if existing is None:
                instance = TournamentRecord(**data)
                instance.created_at = now
                instance.updated_at = now
                session.add(instance)
                stats.inserted += 1
                continue

            changed = existing.update_from_payload(data)
            if changed:
                existing.updated_at = now
                stats.updated += 1
            else:
                stats.skipped += 1

        session.commit()
        self._export_json()
        return stats

    def _export_json(self) -> None:
        session = self._db.session
        rows = session.query(TournamentRecord).order_by(TournamentRecord.start_date.asc()).all()
        payload = [row.to_dict() for row in rows]
        _ensure_directory(self._json_path)
        self._json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


__all__ = ["TournamentStore", "UpsertResult"]

