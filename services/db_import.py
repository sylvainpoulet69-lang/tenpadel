import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from hashlib import sha1
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional

from tenpadel.config_paths import DB_PATH, JSON_PATH, LOG_DIR

LOG_DIR.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("db_import")
if not log.handlers:
    handler = RotatingFileHandler(
        LOG_DIR / "db_import.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DETAIL_ID = re.compile(r"(\d+)(?:[^0-9]*$)")

DB_COLUMNS = [
    "tournament_id",
    "name",
    "level",
    "category",
    "club_name",
    "city",
    "start_date",
    "end_date",
    "detail_url",
    "registration_url",
]


@dataclass(slots=True)
class ImportStats:
    total: int
    valid: int
    inserted: int
    updated: int
    skipped: int
    rows_after: int
    reasons: Dict[str, int]

    def as_dict(self) -> Dict[str, int]:
        return {
            "received": self.total,
            "valid": self.valid,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "db_rows": self.rows_after,
        }


def ensure_schema() -> None:
    """Make sure the tournaments table and supporting indexes exist."""

    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tournaments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id TEXT,
            name TEXT,
            level TEXT,
            category TEXT,
            club_name TEXT,
            city TEXT,
            start_date TEXT,
            end_date TEXT,
            detail_url TEXT NOT NULL UNIQUE,
            registration_url TEXT
        );
        """
    )

    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_detail_url ON tournaments(detail_url);")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_start_date ON tournaments(start_date)"
    )

    # Ensure optional columns exist if the table was created with an older schema.
    cur.execute("PRAGMA table_info(tournaments)")
    existing_columns = {row[1]: row for row in cur.fetchall()}
    if "tournament_id" not in existing_columns:
        cur.execute("ALTER TABLE tournaments ADD COLUMN tournament_id TEXT")
        log.info("Added missing 'tournament_id' column to tournaments table")
    if "registration_url" not in existing_columns:
        cur.execute("ALTER TABLE tournaments ADD COLUMN registration_url TEXT")
        log.info("Added missing 'registration_url' column to tournaments table")
    if "detail_url" in existing_columns and existing_columns["detail_url"][3] == 0:
        log.warning(
            "detail_url column is nullable in existing schema – run Repair-DB.command to rebuild the table"
        )

    con.commit()
    con.close()
    log.debug("Schema ensured at %s", DB_PATH)


def _compute_tournament_id(detail_url: str, explicit: Optional[str]) -> Optional[str]:
    explicit = (explicit or "").strip()
    if explicit:
        return explicit
    detail_url = (detail_url or "").strip()
    if not detail_url:
        return None
    match = DETAIL_ID.search(detail_url)
    if match:
        return match.group(1)
    digest = sha1(detail_url.encode("utf-8")).hexdigest()[:12]
    return f"h{digest}"


def _normalize(item: Mapping[str, object]) -> MutableMapping[str, object]:
    data: Dict[str, object] = dict(item)
    data["detail_url"] = (data.get("detail_url") or data.get("url") or "").strip()
    data["name"] = (data.get("name") or data.get("title") or "Tournoi").strip()

    for key in ("level", "category", "club_name", "city", "start_date", "end_date", "registration_url"):
        value = data.get(key)
        if isinstance(value, str):
            data[key] = value.strip()

    detail_url = str(data.get("detail_url") or "")
    data["tournament_id"] = _compute_tournament_id(detail_url, data.get("tournament_id"))

    start_date = data.get("start_date")
    if isinstance(start_date, str) and start_date and not ISO_DATE.match(start_date):
        log.debug("Non ISO start_date kept as-is: %r for %s", start_date, detail_url)

    return data


def _validate(item: Mapping[str, object]) -> Optional[str]:
    detail_url = (item.get("detail_url") or "").strip()
    if not detail_url:
        return "missing_detail_url"
    if not detail_url.startswith("http"):
        return "bad_detail_url"
    return None


def _row_to_dict(row: sqlite3.Row) -> Dict[str, object]:
    payload = {key: row[key] for key in row.keys()}
    payload["date"] = payload.get("start_date")
    return payload


def import_items(items: Iterable[Mapping[str, object]]) -> ImportStats:
    """Import tournaments and return statistics about the operation."""

    ensure_schema()
    total = 0
    valid: List[MutableMapping[str, object]] = []
    reasons: Dict[str, int] = {}

    for raw in items:
        total += 1
        normalised = _normalize(raw)
        failure = _validate(normalised)
        if failure:
            reasons[failure] = reasons.get(failure, 0) + 1
            continue
        valid.append(normalised)

    log.info(
        "Import batch received=%s valid=%s skipped=%s reasons=%s",
        total,
        len(valid),
        total - len(valid),
        reasons or {},
    )

    if not valid:
        log.warning("No valid tournaments to import; database untouched")
        return ImportStats(total, 0, 0, 0, 0, _count_rows(), reasons)

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    inserted = updated = skipped = 0

    try:
        for item in valid:
            detail_url = item["detail_url"]
            cur.execute(
                "SELECT * FROM tournaments WHERE detail_url = ?",
                (detail_url,),
            )
            existing = cur.fetchone()

            values = tuple(item.get(col) for col in DB_COLUMNS)

            if existing is None:
                cur.execute(
                    """
                    INSERT INTO tournaments(tournament_id, name, level, category, club_name, city,
                                            start_date, end_date, detail_url, registration_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                inserted += 1
                continue

            updates: Dict[str, object] = {}
            for idx, column in enumerate(DB_COLUMNS):
                if column == "detail_url":
                    continue
                new_value = values[idx]
                if new_value in (None, ""):
                    continue
                if existing[column] != new_value:
                    updates[column] = new_value

            if updates:
                set_clause = ", ".join(f"{col} = ?" for col in updates)
                parameters = tuple(updates[col] for col in updates) + (detail_url,)
                cur.execute(
                    f"UPDATE tournaments SET {set_clause} WHERE detail_url = ?",
                    parameters,
                )
                updated += 1
            else:
                skipped += 1

        con.commit()
    except Exception as exc:  # pragma: no cover - defensive logging
        con.rollback()
        log.exception("Import failed: %s", exc)
        raise
    finally:
        con.close()

    rows_after = _count_rows()
    log.info(
        "Import finished inserted=%s updated=%s skipped=%s db_rows_now=%s",
        inserted,
        updated,
        skipped,
        rows_after,
    )

    return ImportStats(total, len(valid), inserted, updated, skipped, rows_after, reasons)


def _count_rows() -> int:
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM tournaments")
    rows = cur.fetchone()[0]
    con.close()
    return int(rows)


def fetch_all_tournaments(limit: Optional[int] = None) -> List[Dict[str, object]]:
    """Return tournaments ordered by start_date ascending (NULL/empty last)."""

    ensure_schema()
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    order_sql = "ORDER BY (start_date IS NULL OR start_date=''), start_date ASC, id DESC"
    limit_sql = " LIMIT ?" if limit else ""
    params: tuple[object, ...] = (limit,) if limit else tuple()
    cur.execute(
        f"SELECT * FROM tournaments {order_sql}{limit_sql}",
        params,
    )
    rows = [_row_to_dict(row) for row in cur.fetchall()]
    con.close()
    return rows


def export_db_to_json(json_path: Path | None = None) -> Path:
    """Export the tournaments table to a JSON file for debugging/backup."""

    destination = json_path or JSON_PATH
    payload = fetch_all_tournaments()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Exported %s tournaments to %s", len(payload), destination)
    return destination


__all__ = [
    "ImportStats",
    "ensure_schema",
    "export_db_to_json",
    "fetch_all_tournaments",
    "import_items",
]
