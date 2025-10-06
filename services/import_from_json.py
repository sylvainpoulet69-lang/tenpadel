"""Utility script to import tournaments from the stored JSON payload."""
from __future__ import annotations

import json

from tenpadel.config_paths import DB_PATH, JSON_PATH
from services.db_import import import_items


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    items = data.get("tournaments", []) if isinstance(data, dict) else []
    inserted = import_items(items)
    print(f"✅ Importé: {inserted} lignes depuis {JSON_PATH} → {DB_PATH}")


if __name__ == "__main__":
    main()
