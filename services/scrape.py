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


def _fr_to_iso(value: str) -> str | None:
    import re

    match = re.search(r"(\d{1,2})\s+([a-zéû\.]+)\s+(\d{4})", value.lower())
    if not match:
        return None
    day = int(match.group(1))
    month = FR_MONTHS.get(match.group(2))
    year = int(match.group(3))
    if not month:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _extract_cards(page, limit: int = 500) -> List[Dict]:
    import re

    items: List[Dict] = []
    seen = -1
    while len(items) < limit and len(items) != seen:
        seen = len(items)
        cards = page.locator("article, div[data-testid='event-card']").all()
        for card in cards:
            if len(items) >= limit:
                break
            try:
                text = card.inner_text()
            except Exception:
                continue
            try:
                heading = card.get_by_role("heading")
                if heading.count():
                    name = heading.first.inner_text().strip()
                else:
                    name = text.splitlines()[0].strip()
            except Exception:
                name = text.splitlines()[0].strip() if text else ""
            if not name:
                continue
            raw_dates = re.findall(r"\d{1,2}\s+[a-zéû\.]+\.?\s+\d{4}", text.lower())
            start_iso = _fr_to_iso(raw_dates[0]) if raw_dates else None
            end_iso = _fr_to_iso(raw_dates[1]) if len(raw_dates) > 1 else start_iso
            level_match = re.search(r"\bP(100|250|500|1000|1500|2000)\b", text)
            level = level_match.group(0) if level_match else None
            cat_match = re.search(r"\bDM(?:\s*/\s*DX)?|\bSM\s*/\s*SD|\bDX\b", text, re.I)
            category = cat_match.group(0).upper().replace(" ", "") if cat_match else None
            location_line = next((line for line in text.splitlines() if "," in line), "")
            club = city = None
            if location_line:
                parts = [segment.strip() for segment in location_line.split(",")]
                if len(parts) > 1:
                    club = ", ".join(parts[:-1])
                    city = parts[-1]
                else:
                    club = parts[0]
                    city = None
            tournament_id = re.sub(
                r"\W+", "-", f"{name}-{start_iso}-{end_iso}"
            ).strip("-").lower()
            if not tournament_id:
                continue
            items.append(
                {
                    "tournament_id": tournament_id,
                    "name": name,
                    "level": level,
                    "category": category,
                    "club_name": club,
                    "city": city,
                    "start_date": start_iso,
                    "end_date": end_iso,
                    "detail_url": None,
                    "registration_url": None,
                }
            )
        page.mouse.wheel(0, 2000)
        time.sleep(0.8)
    return items[:limit]


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
        items = _extract_cards(page, limit=limit)
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
