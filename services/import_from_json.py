import json
from tenpadel.config_paths import JSON_PATH, DB_PATH
from services.db_import import import_items

def main():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    items = data.get("tournaments", [])
    print(f"📄 Lecture JSON: {JSON_PATH}  items={len(items)}")
    rows_after = import_items(items)
    print(f"🗃  DB rows now: {rows_after}  (→ {DB_PATH})")

if __name__ == "__main__":
    main()
