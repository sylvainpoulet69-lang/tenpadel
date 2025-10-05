"""TenUp scraping orchestration usable as a module or CLI."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from playwright.sync_api import sync_playwright

from scrapers.tenup import (
    accept_cookies,
    select_ligue_paca_alpes_maritimes,
    select_discipline_padel,
    apply_sort_by_start_date,
    navigate_to_results,
)



def _extract_cards(page, limit=500, debug=False):
    """
    Extraction tolérante des tournois sur TenUp.
    - Essaie plusieurs sélecteurs de 'cartes'
    - Log le nombre d’éléments par sélecteur (debug)
    - Fallback: dump HTML/PNG si 0 carte
    - Parse: titre, dates FR -> ISO, niveau (Pxxx), catégorie (DM/DX/SM/SD), club/ville
    """
    import re, time, os

    items = []

    # 1) Attendre l'affichage des résultats (si le libellé existe)
    try:
        page.wait_for_selector("text=RÉSULTATS", timeout=12000)
    except Exception:
        pass  # pas bloquant

    # 2) Forcer le chargement par défilement (au cas où)
    for _ in range(8):
        page.mouse.wheel(0, 2200)
        time.sleep(0.6)

    # 3) Essayer plusieurs sélecteurs possibles
    candidate_selectors = [
        "article",
        "div[data-testid='event-card']",
        "li:has(div:has-text('DM'))",
        "div.card, div.card-event",
        "div:has(> div:has-text('DM'))",
    ]

    chosen_cards = []
    best_count = -1
    for sel in candidate_selectors:
        try:
            loc = page.locator(sel)
            cnt = loc.count()
            if debug:
                print(f"[DEBUG] Sélecteur '{sel}' -> {cnt} éléments")
            # Heuristique: prendre le sélecteur qui donne le plus d'éléments
            if cnt > best_count:
                best_count = cnt
                chosen_cards = loc.all()
        except Exception:
            continue

    if debug:
        print(f"[DEBUG] Total cartes retenues: {len(chosen_cards)}")

    # 4) Si rien trouvé, dump la page pour inspection
    if not chosen_cards:
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/last_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            page.screenshot(path="data/last_page.png", full_page=True)
            print("[DEBUG] 0 carte — dump écrit: data/last_page.html / data/last_page.png")
        except Exception:
            pass
        return []

    # 5) Helpers parsing
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

    # 6) Parcours et parsing heuristique
    for c in chosen_cards[:limit]:
        try:
            txt = c.inner_text()

            # Titre
            if c.get_by_role("heading").count():
                name = c.get_by_role("heading").first.inner_text().strip()
            else:
                lines = [l.strip() for l in txt.splitlines() if l.strip()]
                name = lines[0] if lines else "Tournoi"

            # Dates (ex: "5 oct. 2025")
            raw_dates = re.findall(r"\d{1,2}\s+[a-zéû\.]+\.?\s+\d{4}", txt.lower())
            start_date = fr_to_iso(raw_dates[0]) if raw_dates else None
            end_date = fr_to_iso(raw_dates[1]) if len(raw_dates) > 1 else start_date

            # Niveau / Catégorie
            m_level = re.search(r"\bP(100|250|500|1000|1500|2000)\b", txt)
            level = m_level.group(0) if m_level else None
            m_cat = re.search(r"\bDM(?:\s*/\s*DX)?|\bSM\s*/\s*SD|\bDX\b", txt, re.I)
            category = m_cat.group(0).upper().replace(" ", "") if m_cat else None

            # Club / Ville : ligne contenant une virgule
            club = city = None
            loc_line = next((l for l in txt.splitlines() if "," in l), "")
            if loc_line:
                parts = [p.strip() for p in loc_line.split(",")]
                club = ", ".join(parts[:-1]) if len(parts) > 1 else parts[0]
                city = parts[-1] if len(parts) > 1 else None

            # ID stable
            import re as _re

            tid = _re.sub(r"\W+", "-", f"{name}-{start_date}-{end_date}").strip("-").lower()

            items.append(
                {
                    "tournament_id": tid,
                    "name": name,
                    "level": level,
                    "category": category,
                    "club_name": club,
                    "city": city,
                    "start_date": start_date,
                    "end_date": end_date,
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
    from sqlalchemy import Column, Integer, MetaData, String, Table, UniqueConstraint, create_engine

    base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    with open(data_dir / "tournaments.json", "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)

    db_path = data_dir / "app.db"
    engine = create_engine(f"sqlite:///{db_path}")
    metadata = MetaData()
    tournaments = Table(
        "tournaments",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("tournament_id", String, nullable=False),
        Column("name", String),
        Column("level", String),
        Column("category", String),
        Column("club_name", String),
        Column("city", String),
        Column("start_date", String),
        Column("end_date", String),
        Column("detail_url", String),
        Column("registration_url", String),
        UniqueConstraint("tournament_id", name="uq_tournament_id"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        for item in items:
            existing = connection.execute(
                tournaments.select().where(
                    tournaments.c.tournament_id == item["tournament_id"]
                )
            ).fetchone()
            payload = {key: item.get(key) for key in item if key in tournaments.c}
            if existing:
                connection.execute(
                    tournaments.update()
                    .where(tournaments.c.tournament_id == item["tournament_id"])
                    .values(**payload)
                )
            else:
                connection.execute(tournaments.insert().values(**payload))


def scrape_all(
    region: str = "PROVENCE ALPES COTE D’AZUR",
    committee: str = "ALPES MARITIMES",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 500,
) -> List[Dict]:
    """Scrape TenUp tournaments, filter dates, sort and persist results."""

    def to_dt(value: str | None) -> datetime | None:
        return datetime.strptime(value, "%Y-%m-%d") if value else None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="fr-FR", viewport={"width": 1440, "height": 900})
        page.goto("https://tenup.fft.fr/recherche/tournois", wait_until="networkidle")
        accept_cookies(page)
        select_ligue_paca_alpes_maritimes(page)
        select_discipline_padel(page)
        apply_sort_by_start_date(page)
        navigate_to_results(page)

        # forcer à charger plus d’éléments (si lazy-load)
        for _ in range(8):
            page.mouse.wheel(0, 2200)
            time.sleep(0.6)

        items = _extract_cards(page, limit=limit, debug=True)   # 1er run en debug
        browser.close()

    if date_from:
        lower = to_dt(date_from)
        items = [item for item in items if item["start_date"] and to_dt(item["start_date"]) >= lower]
    if date_to:
        upper = to_dt(date_to)
        items = [item for item in items if item["end_date"] and to_dt(item["end_date"]) <= upper]

    items.sort(key=lambda entry: (entry["start_date"] or "9999-99-99"))
    _save_results(items)
    return items


# --- compatibilité legacy pour app.py

def scrape_tenup(
    region: str = "PROVENCE ALPES COTE D’AZUR",
    committee: str = "ALPES MARITIMES",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 500,
):
    """Alias backward-compat: certains modules importent 'scrape_tenup'."""

    return scrape_all(
        region=region,
        committee=committee,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape TenUp tournaments (UI only)")
    parser.add_argument("--region", default="PROVENCE ALPES COTE D’AZUR")
    parser.add_argument("--committee", default="ALPES MARITIMES")
    parser.add_argument("--date-from", dest="date_from")
    parser.add_argument("--date-to", dest="date_to")
    parser.add_argument("--limit", type=int, default=500)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    results = scrape_all(
        region=args.region,
        committee=args.committee,
        date_from=args.date_from,
        date_to=args.date_to,
        limit=args.limit,
    )
    print(f"🎯 TenUp scraping terminé – {len(results)} tournois")
    print("   → Export JSON : data/tournaments.json")
    print("   → Base SQLite: data/app.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
