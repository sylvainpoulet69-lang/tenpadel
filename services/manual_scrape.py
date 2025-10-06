"""Manual TenUp scraper where the user applies filters by hand."""
from __future__ import annotations

import json, time
import re
import sys
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright

OUTPUT_FILE = "data/tournaments.json"
SNAPSHOT_FILE = "data/snapshot.html"


def _ensure_data_dir() -> Path:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


DEFAULT_FFT_URL = "https://tenup.fft.fr/recherche/tournois"
LEVEL_RE = re.compile(r"\bP(?:100|250|500|1000|1500|2000)\b", re.I)
CAT_RE = re.compile(r"\b(?:DM|DX|SM|SD)\b", re.I)


def extract_tournaments(html: str) -> list[dict]:
    # lxml est plus robuste que html.parser
    soup = BeautifulSoup(html, "lxml")

    # Conteneurs larges (PAS de :has / :has-text)
    candidates = []
    for sel in [
        ".tenup-card",  # ancien markup TenUp
        "div.card, div.card-event",  # cartes génériques
        "[data-testid='event-card']",  # si présent
        "article",  # fallback
        "li",  # fallback très large
    ]:
        found = soup.select(sel)
        if len(found) > len(candidates):
            candidates = found

    items, seen = [], set()

    for c in candidates:
        text = c.get_text(" ", strip=True)

        # Garder les éléments qui semblent être des tournois de Padel
        if not (LEVEL_RE.search(text) or CAT_RE.search(text) or "padel" in text.lower()):
            continue

        def sel_txt(css):
            el = c.select_one(css)
            return el.get_text(strip=True) if el else ""

        title = (
            sel_txt(".tenup-card__title")
            or sel_txt("h3, h4, h2")
            or (text.split(" • ")[0] if text else "")
        )
        date = sel_txt(".tenup-card__date") or sel_txt(".date") or sel_txt("time")
        place = sel_txt(".tenup-card__place") or sel_txt(".location") or sel_txt("p")

        level = sel_txt(".tenup-card__category") or sel_txt(".category")
        if not level:
            m = LEVEL_RE.search(text)
            level = m.group(0) if m else ""

        a = c.select_one("a[href]")
        url = a["href"] if (a and a.has_attr("href")) else DEFAULT_FFT_URL  # ← URL par défaut

        key = url or f"{title}|{date}"
        if key in seen:
            continue
        seen.add(key)

        items.append({
            "title": title,
            "date": date,
            "place": place,
            "level": level,
            "url": url,
        })

    return items


def go_next_page(page: Page) -> bool:
    """
    Essaie de cliquer sur 'Page suivante' via plusieurs sélecteurs.
    Retourne True si une nouvelle page s'affiche, sinon False.
    """
    selectors = [
        "button[aria-label='Page suivante']",
        "a[aria-label='Page suivante']",
        "button:has-text('Page suivante')",
        "a:has-text('Page suivante')",
        "button:has-text('Suivante')",
        "a[rel='next']",
        "nav[aria-label='Pagination'] a[rel='next']",
    ]

    before = page.content()

    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() == 0:
                continue
            el = loc.first
            el.wait_for(state="visible", timeout=2000)
            if not el.is_enabled():
                continue
            el.scroll_into_view_if_needed()
            el.click()
            page.wait_for_timeout(800)
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            after = page.content()
            if after != before:
                return True
        except Exception:
            continue

    return False


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

            snapshot_path = data_dir / Path(SNAPSHOT_FILE).name
            all_tournaments: list[dict] = []
            seen: set[str] = set()
            page_index = 1
            MAX_PAGES = 500  # garde-fou

            while True:
                html = page.content()
                with open(snapshot_path, "w", encoding="utf-8") as snap:
                    snap.write(html)

                batch = extract_tournaments(html)

                for t in batch:
                    key = t["url"] or f"{t['title']}|{t['date']}"
                    if key not in seen:
                        seen.add(key)
                        all_tournaments.append(t)

                print(f"➡️ Page {page_index}: {len(batch)} trouvés, total {len(all_tournaments)}")

                if page_index >= MAX_PAGES:
                    print("⛔️ Arrêt sécurité: trop de pages.")
                    break

                if go_next_page(page):
                    page_index += 1
                    continue
                else:
                    break

            output_path = data_dir / Path(OUTPUT_FILE).name
            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump(all_tournaments, handle, ensure_ascii=False, indent=2)

            print(f"\n✅ Total unique: {len(all_tournaments)} tournois")
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
