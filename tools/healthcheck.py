# tools/healthcheck.py
import json, sqlite3, time, re, urllib.request, sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DB   = DATA / "app.db"
JSONF= DATA / "tournaments.json"
LOGD = DATA / "logs"
API  = "http://127.0.0.1:5000/api/tournaments"

def stamp(p: Path):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
    except Exception:
        return "—"

def out_lines(lines):
    LOGD.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rpt = LOGD / f"health-{ts}.txt"
    rpt.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📄 Rapport: {rpt}")
    return rpt

def main():
    ok = True
    L  = []
    L.append("=== TenPadel Healthcheck ===")

    # 1) FICHIERS
    L.append("\n[FILES]")
    L.append(f"json: {JSONF}  exists={JSONF.exists()}  mtime={stamp(JSONF)}")
    L.append(f"db:   {DB}     exists={DB.exists()}     mtime={stamp(DB)}")

    # 2) JSON
    json_count = dated_json = 0
    first_date = last_date = None
    if JSONF.exists():
        try:
            data = json.loads(JSONF.read_text(encoding="utf-8"))
            items = data.get("tournaments", [])
            json_count = len(items)
            for t in items:
                d = (t.get("start_date") or t.get("date") or "").strip() or None
                if d:
                    dated_json += 1
                    if not first_date or d < first_date:
                        first_date = d
                    if not last_date or d > last_date:
                        last_date = d
            L.append(f"[JSON] tournaments={json_count}  with_start_date={dated_json}  range={first_date}..{last_date}")
            if json_count == 0:
                ok = False
                L.append("!! JSON present mais vide -> vérifier le scrap")
        except Exception as e:
            ok = False
            L.append(f"!! JSON illisible: {e}")
    else:
        L.append(".. JSON manquant (ok si on ne l'utilise pas)")

    # 3) DB
    db_total = db_dated = 0
    if DB.exists():
        try:
            con = sqlite3.connect(str(DB))
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tournaments'")
            if not cur.fetchone():
                ok = False
                L.append("!! Table 'tournaments' absente")
            else:
                cur.execute("SELECT COUNT(*) FROM tournaments")
                db_total = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM tournaments WHERE COALESCE(start_date,'')!=''")
                db_dated = cur.fetchone()[0]
                cur.execute("SELECT MIN(start_date), MAX(start_date) FROM tournaments WHERE COALESCE(start_date,'')!=''")
                db_min, db_max = cur.fetchone()
                L.append(f"[DB] rows={db_total}  with_start_date={db_dated}  range={db_min}..{db_max}")
                if db_total == 0:
                    ok = False
                    L.append("!! DB vide -> import non exécuté")
        finally:
            try:
                con.close()
            except Exception:
                pass
    else:
        L.append(".. DB manquante -> import non exécuté")

    # 4) API
    api_count = 0
    try:
        with urllib.request.urlopen(API, timeout=5) as r:
            body = r.read().decode("utf-8", errors="ignore")
            # comptage simple
            api_count = body.count('"detail_url"')
            L.append(f"[API] /api/tournaments -> ~{api_count} objets")
    except Exception as e:
        ok = False
        L.append(f"!! API injoignable: {e}")

    # 5) HEURISTIQUES D’ERREURS COURANTES
    L.append("\n[DIAG]")
    if DB.exists() and db_total > 0 and api_count == 0:
        L.append("• DB contient des lignes mais l’API renvoie 0 -> très probable: l’UI/app applique encore des filtres par défaut OU l’API filtre trop strict.")
        L.append("  -> Solution : appel initial du front SANS query params; endpoint /api/tournaments doit renvoyer tout (tri par start_date).")
    if db_total > 0 and db_dated == 0:
        ok = False
        L.append("• Aucune start_date en DB -> le scraper doit convertir la date FR en YYYY-MM-DD puis importer ces valeurs.")
    if json_count > 0 and dated_json == 0:
        L.append("• JSON sans start_date -> même cause; on peut parse côté scraper.")

    # 6) Résumé + code retour
    L.append("\n[SUMMARY]")
    L.append(f"OK={ok}  (json={json_count}, db={db_total}, api≈{api_count})")
    out_lines(L)
    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
