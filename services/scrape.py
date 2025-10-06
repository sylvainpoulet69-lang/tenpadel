"""TenUp scraping orchestration usable as a module or CLI."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from typing import Dict, List

from playwright.sync_api import sync_playwright

from scrapers.tenup import accept_cookies, navigate_to_results, select_discipline_padel
from services.db_import import export_db_to_json, import_items
from tenpadel.config_paths import JSON_PATH



def _extract_cards(page, limit=500, debug=False):
    import os
    import re

    items = []

    try:
        page.wait_for_selector("text=RÉSULTATS", timeout=10000)
    except Exception:
        pass

    candidates = [
        "div[data-testid='event-card']",
        "article",
        "li:has(div:has-text('DM'))",
        "div.card, div.card-event",
        "div:has(> div:has-text('DM'))",
    ]

    best = []
    best_count = -1
    for sel in candidates:
        try:
            loc = page.locator(sel)
            cnt = loc.count()
            if debug:
                print(f"[DEBUG] Sélecteur '{sel}' -> {cnt} éléments")
            if cnt > best_count:
                best, best_count = loc.all(), cnt
        except Exception:
            continue
    if debug:
        print(f"[DEBUG] Total cartes retenues: {len(best)}")

    if not best:
        if debug:
            os.makedirs("data", exist_ok=True)
            with open("data/last_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            page.screenshot(path="data/last_page.png", full_page=True)
            print("[DEBUG] 0 carte — dump écrit: data/last_page.html / data/last_page.png")
        return []

    FR_MONTHS = {
        "janv": 1,
        "jan.": 1,
        "févr": 2,
        "fév.": 2,
        "mars": 3,
        "avr": 4,
        "avr.": 4,
        "mai": 5,
        "juin": 6,
        "juil": 7,
        "juil.": 7,
        "août": 8,
        "sept": 9,
        "sep.": 9,
        "oct": 10,
        "oct.": 10,
        "nov": 11,
        "déc": 12,
        "déc.": 12,
    }

    def fr_to_iso(s: str) -> str | None:
        m = re.search(r"(\d{1,2})\s+([a-zéû\.]+)\s+(\d{4})", s.lower())
        if not m:
            return None
        d, mo, y = int(m.group(1)), FR_MONTHS.get(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}" if mo else None

    for c in best[:limit]:
        try:
            txt = c.inner_text()
            name = (
                c.get_by_role("heading").first.inner_text().strip()
                if c.get_by_role("heading").count()
                else (txt.splitlines()[0].strip() if txt else "Tournoi")
            )
            dates = re.findall(r"\d{1,2}\s+[a-zéû\.]+\.?\s+\d{4}", txt.lower())
            s_iso = fr_to_iso(dates[0]) if dates else None
            e_iso = fr_to_iso(dates[1]) if len(dates) > 1 else s_iso
            m_level = re.search(r"\bP(100|250|500|1000|1500|2000)\b", txt)
            level = m_level.group(0) if m_level else None
            m_cat = re.search(r"\bDM(?:\s*/\s*DX)?|\bSM\s*/\s*SD|\bDX\b", txt, re.I)
            category = m_cat.group(0).upper().replace(" ", "") if m_cat else None
            club = city = None
            loc_line = next((l for l in txt.splitlines() if "," in l), "")
            if loc_line:
                parts = [p.strip() for p in loc_line.split(",")]
                club = ", ".join(parts[:-1]) if len(parts) > 1 else parts[0]
                city = parts[-1] if len(parts) > 1 else None
            import re as _re

            tid = _re.sub(r"\W+", "-", f"{name}-{s_iso}-{e_iso}").strip("-").lower()
            items.append(
                {
                    "tournament_id": tid,
                    "name": name,
                    "level": level,
                    "category": category,
                    "club_name": club,
                    "city": city,
                    "start_date": s_iso,
                    "end_date": e_iso,
                    "detail_url": None,
                    "registration_url": None,
                }
            )
        except Exception:
            continue
    if debug:
        print(f"[DEBUG] Items extraits: {len(items)}")
    return items



def _save_results(items: List[Dict]) -> None:
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = import_items(items)
    export_db_to_json()
    print(
        "Import:"
        f" inserted={stats.inserted} updated={stats.updated} skipped={stats.skipped}"
        f" db_rows={stats.rows_after}"
    )


def scrape_all(
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 500,
    debug: bool = False,
) -> List[Dict]:
    """Scrape TenUp tournaments, filter/sort client-side and persist results."""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="fr-FR", viewport={"width": 1440, "height": 900})
        page.goto("https://tenup.fft.fr/recherche/tournois", wait_until="networkidle")
        accept_cookies(page)
        select_discipline_padel(page)
        navigate_to_results(page)

        last = -1
        for _ in range(16):
            page.mouse.wheel(0, 2400)
            time.sleep(0.5)
            count = page.locator("body *").count()
            if count == last:
                break
            last = count

        items = _extract_cards(page, limit=limit, debug=debug)
        browser.close()

    def to_dt(value: str | None) -> datetime | None:
        return datetime.strptime(value, "%Y-%m-%d") if value else None

    if date_from:
        lower = to_dt(date_from)
        items = [item for item in items if item["start_date"] and to_dt(item["start_date"]) >= lower]
    if date_to:
        upper = to_dt(date_to)
        items = [item for item in items if item["end_date"] and to_dt(item["end_date"]) <= upper]

    items.sort(key=lambda x: (x["start_date"] or "9999-99-99"))
    _save_results(items)
    print(f"✅ TenUp scraping terminé — {len(items)} tournois")
    return items


# --- compatibilité legacy pour app.py

def scrape_tenup(**kwargs):
    """Backward-compatible alias for historical imports."""

    return scrape_all(**kwargs)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape TenUp tournaments (UI only)")
    parser.add_argument("--date-from", dest="date_from")
    parser.add_argument("--date-to", dest="date_to")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--debug", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    results = scrape_all(
        date_from=args.date_from,
        date_to=args.date_to,
        limit=args.limit,
        debug=args.debug,
    )
    print(f"🎯 TenUp scraping terminé – {len(results)} tournois")
    print("   → Export JSON : data/tournaments.json")
    print("   → Base SQLite: data/app.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
