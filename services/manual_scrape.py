"""Manual TenUp scraper where the user applies filters by hand."""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUTPUT_FILE = "data/tournaments.json"
SNAPSHOT_FILE = "data/snapshot.html"


def _ensure_data_dir() -> Path:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _extract_tournaments(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    cards: list[Any] = []
    for sel in [
        ".tenup-card",
        "li:has(div:has-text('P'))",
        "div.card, div.card-event",
        "article",
        "div[data-testid='event-card']",
    ]:
        found = soup.select(sel)
        if len(found) > len(cards):
            cards = found

    tournaments: list[dict] = []
    for card in cards:
        def txt(selector: str) -> str:
            el = card.select_one(selector)
            return el.get_text(strip=True) if el else ""

        title = (
            txt(".tenup-card__title")
            or txt("h3, h4, h2")
            or (card.get_text(" ", strip=True).split(" • ")[0] if card.get_text(strip=True) else "")
        )
        date = txt(".tenup-card__date") or txt(".date") or txt("time") or ""
        place = txt(".tenup-card__place") or txt(".location") or txt("p") or ""
        level = txt(".tenup-card__category") or txt(".category") or ""
        if not level:
            match = re.search(r"\bP(?:100|250|500|1000|1500|2000)\b", card.get_text(" ", strip=True))
            level = match.group(0) if match else ""

        anchor = card.select_one("a[href]")
        url = anchor["href"] if anchor and anchor.has_attr("href") else ""

        tournaments.append({
            "title": title,
            "date": date,
            "place": place,
            "level": level,
            "url": url,
        })

    return tournaments


def _slugify(value: str) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value)
    return value.strip("-").lower()


def _split_place(place: str) -> tuple[str | None, str | None]:
    if not place:
        return None, None
    for sep in (" - ", " • ", " | ", " •", "-", ","):
        if sep in place:
            parts = [p.strip() for p in place.split(sep) if p.strip()]
            if len(parts) >= 2:
                return parts[0], parts[-1]
    return place.strip() or None, None


def _upsert_database(items: list[dict]) -> None:
    from sqlalchemy import (
        Column,
        Integer,
        MetaData,
        String,
        Table,
        UniqueConstraint,
        create_engine,
        inspect,
        insert,
        select,
        update,
    )

    data_dir = _ensure_data_dir()
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
        Column("detail_url", String, nullable=True),
        Column("registration_url", String, nullable=True),
        UniqueConstraint("tournament_id", name="uq_tournament_id"),
        extend_existing=True,
    )
    metadata.create_all(engine)

    # Warn user if existing schema enforces non-null constraints for optional URLs
    try:
        inspector = inspect(engine)
        cols = inspector.get_columns("tournaments")
        for optional in ("detail_url", "registration_url"):
            info = next((col for col in cols if col["name"] == optional), None)
            if info and not info.get("nullable", True):
                print(
                    "⚠️  La base SQLite existe déjà avec une contrainte NOT NULL sur"
                    f" {optional}. Pensez à recréer data/app.db si besoin."
                )
                break
    except Exception:
        pass

    def _normalize(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    with engine.begin() as conn:
        for item in items:
            slug_source = item.get("url") or f"{item.get('title', '')}-{item.get('date', '')}"
            tournament_id = _slugify(slug_source) or _slugify(f"{item.get('title', '')}-{item.get('date', '')}-{time.time()}")
            club, city = _split_place(item.get("place", ""))
            payload = {
                "tournament_id": tournament_id,
                "name": _normalize(item.get("title")),
                "level": _normalize(item.get("level")),
                "category": None,
                "club_name": _normalize(club),
                "city": _normalize(city),
                "start_date": None,
                "end_date": None,
                "detail_url": _normalize(item.get("url")),
                "registration_url": None,
            }

            existing = conn.execute(
                select(tournaments.c.id).where(tournaments.c.tournament_id == tournament_id)
            ).fetchone()

            if existing:
                conn.execute(
                    update(tournaments)
                    .where(tournaments.c.tournament_id == tournament_id)
                    .values(**payload)
                )
            else:
                conn.execute(insert(tournaments).values(**payload))


def manual_scrape(start_url: str = "https://tenup.fft.fr/recherche/tournois") -> None:
    data_dir = _ensure_data_dir()
    print("\n=== SCRAPER LES TOURNOIS PADEL (mode manuel) ===")
    print("1) Une fenêtre Chromium va s’ouvrir.")
    print("2) Connecte-toi si besoin, applique TES FILTRES (PADEL uniquement).")
    print("3) Quand la page de résultats est visible et filtrée, reviens ici et appuie sur Entrée.\n")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            page = browser.new_page()
            page.goto(start_url, wait_until="domcontentloaded")
            print(f"✅ Page ouverte : {start_url}")

            input("👉 Appuie sur Entrée pour démarrer le scraping de la page courante… ")

            all_items: list[dict] = []
            seen_keys: set[str] = set()

            while True:
                html = page.content()
                snapshot_path = data_dir / Path(SNAPSHOT_FILE).name
                with open(snapshot_path, "w", encoding="utf-8") as snap:
                    snap.write(html)

                batch = _extract_tournaments(html)

                for item in batch:
                    key = item.get("url") or f"{item.get('title', '')}|{item.get('date', '')}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_items.append(item)

                next_candidates = [
                    page.get_by_role("button", name="Page suivante"),
                    page.locator('button[aria-label="Page suivante"]'),
                    page.get_by_text("Page suivante"),
                    page.locator("a[rel=next], button:has-text('Suivante'), a:has-text('Suivante')"),
                ]
                clicked = False
                for locator in next_candidates:
                    try:
                        count = locator.count()
                        if not count:
                            continue
                        target = locator.first if count > 1 else locator
                        if target.is_enabled():
                            target.click()
                            time.sleep(2)
                            clicked = True
                            break
                    except Exception:
                        continue

                if not clicked:
                    break

            output_path = data_dir / Path(OUTPUT_FILE).name
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump(all_items, handle, ensure_ascii=False, indent=2)

            print(f"\n✅ Total unique: {len(all_items)} tournois")
            print(f"📁 Résultats : {output_path}")
            print(f"🧾 Snapshot : {snapshot_path}")

        finally:
            browser.close()

    try:
        with open(data_dir / Path(OUTPUT_FILE).name, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload:
            _upsert_database(payload)
            print("🗄️  Base SQLite mise à jour : data/app.db")
    except Exception as exc:  # pragma: no cover - best effort
        print(f"⚠️  Impossible de mettre à jour la base SQLite: {exc}", file=sys.stderr)


if __name__ == "__main__":
    manual_scrape()
