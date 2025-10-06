"""Repair the SQLite database schema and reload tournaments from JSON."""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from services.db_import import ImportStats, ensure_schema, import_items
from tenpadel.config_paths import DB_PATH, JSON_PATH, LOG_DIR


def backup_database() -> Path | None:
    if not DB_PATH.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = DB_PATH.with_name(f"{DB_PATH.name}.bak-{timestamp}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def recreate_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS tournaments")
    cur.execute("DROP INDEX IF EXISTS idx_unique_detail_url")
    cur.execute("DROP INDEX IF EXISTS idx_start_date")
    con.commit()
    con.close()
    ensure_schema()


def read_json_payload() -> list[dict]:
    if not JSON_PATH.exists():
        print(f"⚠️  JSON file missing: {JSON_PATH}")
        return []
    raw = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [dict(item) for item in raw]
    if isinstance(raw, dict):
        candidates = raw.get("tournaments") or raw.get("items") or []
        if isinstance(candidates, list):
            return [dict(item) for item in candidates]
    print(f"⚠️  Unsupported JSON structure in {JSON_PATH}")
    return []


def import_current_json() -> ImportStats:
    items = read_json_payload()
    print(f"📥 Importing {len(items)} tournaments from {JSON_PATH}")
    return import_items(items)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    backup = backup_database()
    if backup:
        print(f"🗃️  Backup created: {backup}")

    recreate_schema()
    print("✅ Schema recreated")

    stats = import_current_json()
    print(
        "   ↳ Inserted: {0.inserted}  Updated: {0.updated}  Unchanged: {0.skipped}".format(stats)
    )
    if stats.reasons:
        print(f"   ↳ Ignored: {stats.total - stats.valid} {stats.reasons}")
    print(f"📊 Database rows: {stats.rows_after} (file: {DB_PATH})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
