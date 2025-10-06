"""Compatibility wrapper for legacy TournamentStore usage."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from services.db_import import export_db_to_json, import_items


@dataclass(slots=True)
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

    def __init__(self, _db, json_path: Path) -> None:  # pragma: no cover - compatibility signature
        self._json_path = json_path
        self._json_path.parent.mkdir(parents=True, exist_ok=True)

    def upsert_many(self, records: Iterable[Mapping[str, object]]) -> UpsertResult:
        stats = import_items(records)
        self._export_json()
        return UpsertResult(
            inserted=stats.inserted,
            updated=stats.updated,
            skipped=stats.skipped,
        )

    def _export_json(self) -> None:
        export_db_to_json(self._json_path)


__all__ = ["TournamentStore", "UpsertResult"]

