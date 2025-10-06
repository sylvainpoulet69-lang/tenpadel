import json
from tenpadel.config_paths import JSON_PATH, DB_PATH
from services.db_import import import_items

def main():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    items = data.get("tournaments", [])
    print(f"📄 Lecture JSON: {JSON_PATH}  items={len(items)}")
    stats = import_items(items)
    print(
        f"   ↳ Inserted: {stats.inserted}  Updated: {stats.updated}  Unchanged: {stats.skipped}"
    )
    if stats.reasons:
        print(f"   ↳ Ignored: {stats.total - stats.valid} {stats.reasons}")
    print(f"🗃  DB rows now: {stats.rows_after}  (→ {DB_PATH})")

if __name__ == "__main__":
    main()
