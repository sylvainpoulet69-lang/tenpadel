import re, sqlite3, logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Dict

# chemins uniques
from tenpadel.config_paths import DB_PATH, LOG_DIR

LOG_DIR.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("db_import")
if not log.handlers:
    fh = RotatingFileHandler(LOG_DIR / "db_import.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh); log.setLevel(logging.INFO)

COLUMNS = ["name","level","category","club_name","city","start_date","end_date","detail_url","registration_url"]
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def ensure_schema():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH)); cur = con.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS tournaments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, level TEXT, category TEXT, club_name TEXT, city TEXT,
        start_date TEXT, end_date TEXT,
        detail_url TEXT NOT NULL UNIQUE,
        registration_url TEXT
      );
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_detail_url ON tournaments(detail_url);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_start_date ON tournaments(start_date);")
    con.commit(); con.close()
    log.info("Schema ensured at %s", DB_PATH)

def _normalize(it: Dict) -> Dict:
    it = dict(it)  # shallow copy
    # alias + trims
    it["detail_url"] = (it.get("detail_url") or it.get("url") or "").strip()
    it["name"] = (it.get("name") or it.get("title") or "Tournoi").strip()
    for k in ["level","category","club_name","city","start_date","end_date","registration_url"]:
        if k in it and isinstance(it[k], str):
            it[k] = it[k].strip()
    # dates : garder vide si non-ISO, on loguera
    if it.get("start_date") and not ISO_DATE.match(it["start_date"]):
        log.debug("non ISO start_date, keep-as-is: %r for %s", it["start_date"], it["detail_url"])
    return it

def _validate(it: Dict) -> str | None:
    if not it.get("detail_url"):
        return "missing_detail_url"
    if not it["detail_url"].startswith("http"):
        return "bad_detail_url"
    return None  # ok

def import_items(items: List[Dict]) -> int:
    ensure_schema()
    total = len(items)
    valid = []
    reasons = {}
    for it in items:
        it = _normalize(it)
        err = _validate(it)
        if err:
            reasons[err] = reasons.get(err, 0) + 1
            continue
        valid.append(tuple(it.get(k) for k in COLUMNS))

    log.info("Incoming items=%s  valid=%s  skipped=%s %s",
             total, len(valid), total-len(valid), reasons if reasons else "")

    if not valid:
        log.warning("No valid items to import (DB untouched).")
        return 0

    con = sqlite3.connect(str(DB_PATH)); cur = con.cursor()

    # UPSERT: si detail_url déjà présent, on met à jour quelques champs utiles
    q = """
    INSERT INTO tournaments(name,level,category,club_name,city,start_date,end_date,detail_url,registration_url)
    VALUES (?,?,?,?,?,?,?,?,?)
    ON CONFLICT(detail_url) DO UPDATE SET
      name=excluded.name,
      category=COALESCE(excluded.category, tournaments.category),
      club_name=COALESCE(excluded.club_name, tournaments.club_name),
      city=COALESCE(excluded.city, tournaments.city),
      start_date=COALESCE(excluded.start_date, tournaments.start_date),
      end_date=COALESCE(excluded.end_date, tournaments.end_date),
      registration_url=COALESCE(excluded.registration_url, tournaments.registration_url)
    ;
    """
    cur.executemany(q, valid)
    con.commit()

    # comptage après import
    cur.execute("SELECT COUNT(*) FROM tournaments")
    rows = cur.fetchone()[0]
    con.close()

    # ATTENTION: sqlite3.rowcount après executemany n'est pas fiable → on recompte
    log.info("Import finished: db_rows_now=%s (db=%s)", rows, DB_PATH)
    return rows
