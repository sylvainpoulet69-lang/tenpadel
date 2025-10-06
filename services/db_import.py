import sqlite3
from pathlib import Path
from typing import List, Dict

BASE = Path(__file__).resolve().parent.parent
DB    = BASE / "data" / "app.db"

COLUMNS = [
    "name","level","category","club_name","city",
    "start_date","end_date","detail_url","registration_url"
]

def ensure_schema():
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tournaments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_detail_url ON tournaments(detail_url);")
    con.commit()
    con.close()

def _row(it: Dict):
    # alias + garde-fous
    if not it.get("detail_url") and it.get("url"):
        it["detail_url"] = it["url"]
    if not it.get("detail_url"):
        return None
    it["name"] = (it.get("name") or it.get("title") or "Tournoi").strip()
    return tuple((it.get(k) if k != "name" else it["name"]) for k in COLUMNS)

def import_items(items: List[Dict]) -> int:
    """INSERT OR IGNORE par detail_url (idempotent). Renvoie le nb de nouvelles lignes."""
    ensure_schema()
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    q = f"INSERT OR IGNORE INTO tournaments({','.join(COLUMNS)}) VALUES ({','.join(['?']*len(COLUMNS))})"
    ok = 0
    for it in items:
        tup = _row(it)
        if not tup:
            continue
        cur.execute(q, tup)
        ok += cur.rowcount
    con.commit()
    con.close()
    return ok
