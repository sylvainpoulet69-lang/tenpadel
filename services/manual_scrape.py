"""Manual TenUp scraper where the user applies filters by hand."""
from __future__ import annotations

import json
import time
import os
import re
import sys
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page

OUTPUT_FILE = "data/tournaments.json"
SNAPSHOT_FILE = "data/snapshot.html"

DEFAULT_FFT_URL = "https://tenup.fft.fr/recherche/tournois"

# Catégories & niveaux attendus
CAT_RE = re.compile(r"\b(?:DM|DX|DD|SM|SD)\b", re.I)
LEVEL_RE = re.compile(r"\bP(?:100|250|500|1000|1500|2000)\b", re.I)

# Dates françaises compactes « 21 nov. 2025 » / « 7 févr. 2026 » / « 30 nov 2025 »
DATE_RE = re.compile(
    r"\b(\d{1,2})\s*(janv\.|févr\.|mars|avr\.|mai|juin|juil\.|août|sept\.|oct\.|nov\.|déc\.)\s*(\d{4})\b",
    re.I,
)


def _ensure_data_dir():
    Path("data").mkdir(parents=True, exist_ok=True)


def extract_tournaments(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")

    # Conteneurs « larges » — PAS de :has / :has-text
    candidates = []
    for sel in [
        ".tenup-card",                    # ancien markup
        "div.card, div.card-event",       # cartes génériques
        "[data-testid='event-card']",
        "article",
        "li",
    ]:
        found = soup.select(sel)
        if len(found) > len(candidates):
            candidates = found

    items, seen = [], set()

    for c in candidates:
        text = c.get_text(" ", strip=True)

        # Si on ne voit aucun indice Padel, on ignore (mais reste permissif)
        if not (LEVEL_RE.search(text) or CAT_RE.search(text) or "padel" in text.lower()):
            continue

        def sel_txt(css):
            el = c.select_one(css)
            return el.get_text(strip=True) if el else ""

        # Titre (gros texte à gauche)
        title = (
            sel_txt(".tenup-card__title")
            or sel_txt("h3, h4, h2")
            or (text.split(" • ")[0] if text else "")
        )

        # Lieu (ligne avec l’icône localisation)
        place = (
            sel_txt(".tenup-card__place")
            or sel_txt(".location")
            or sel_txt("p")
        )

        # Catégorie : pilule type DM / DX / DD / SM / SD
        # On cherche d’abord des éléments typés, sinon on retombe sur le texte global
        category = (
            sel_txt(".tenup-card__category")
            or sel_txt(".category")
        )
        if not category:
            m = CAT_RE.search(text)
            category = m.group(0).upper() if m else "Inconnue"

        # Niveaux (P100 / P250 / etc.) — facultatif mais utile
        level = (
            sel_txt(".tenup-card__level")
            or sel_txt(".level")
        )
        if not level:
            m = LEVEL_RE.search(text)
            level = m.group(0).upper() if m else ""

        # Dates : on tente d’extraire deux occurrences (début / fin) dans le bloc de droite
        # On cherche dans la carte elle-même d'abord
        dates_text = (
            sel_txt(".tenup-card__date")
            or sel_txt(".date")
            or text
        )
        date_matches = DATE_RE.findall(dates_text)
        start_date = end_date = ""
        if len(date_matches) >= 1:
            d, m, y = date_matches[0]
            start_date = f"{d} {m} {y}"
        if len(date_matches) >= 2:
            d, m, y = date_matches[1]
            end_date = f"{d} {m} {y}"

        # Lien
        a = c.select_one("a[href]")
        url = a["href"] if (a and a.has_attr("href")) else DEFAULT_FFT_URL

        # Unicité
        key = url or f"{title}|{start_date}|{end_date}"
        if key in seen:
            continue
        seen.add(key)

        items.append({
            "title":      title or "Tournoi sans titre",
            "place":      place or "Lieu inconnu",
            "category":   category or "Inconnue",
            "level":      level or "Niveau non précisé",
            "start_date": start_date or "Date inconnue",
            "end_date":   end_date or "Date inconnue",
            "url":        url,
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


def sanitize_tournament(t: dict) -> dict:
    # Valeurs par défaut si vides
    return {
        "title":      (t.get("title") or "Tournoi sans titre").strip(),
        "place":      (t.get("place") or "Lieu inconnu").strip(),
        "category":   (t.get("category") or "Inconnue").strip(),
        "level":      (t.get("level") or "Niveau non précisé").strip(),
        "start_date": (t.get("start_date") or "Date inconnue").strip(),
        "end_date":   (t.get("end_date") or "Date inconnue").strip(),
        "url":        (t.get("url") or DEFAULT_FFT_URL).strip(),
    }


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

    _ensure_data_dir()
    db_path = Path("data") / "app.db"
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
            slug_source = item.get("url") or f"{item.get('title', '')}-{item.get('start_date', '')}-{item.get('end_date', '')}"
            tournament_id = _slugify(slug_source) or _slugify(
                f"{item.get('title', '')}-{item.get('start_date', '')}-{item.get('end_date', '')}-{time.time()}"
            )
            club, city = _split_place(item.get("place", ""))
            payload = {
                "tournament_id": tournament_id,
                "name": _normalize(item.get("title")),
                "level": _normalize(item.get("level")),
                "category": _normalize(item.get("category")),
                "club_name": _normalize(club),
                "city": _normalize(city),
                "start_date": _normalize(item.get("start_date")),
                "end_date": _normalize(item.get("end_date")),
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
    _ensure_data_dir()
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

            all_tournaments: list[dict] = []
            seen: set[str] = set()
            page_index = 1
            MAX_PAGES = 500  # garde-fou

            while True:
                html = page.content()
                batch = extract_tournaments(html)

                for t in batch:
                    t = sanitize_tournament(t)
                    key = t["url"] or f"{t['title']}|{t['start_date']}|{t['end_date']}"
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

            with open("data/tournaments.json", "w", encoding="utf-8") as handle:
                json.dump(all_tournaments, handle, ensure_ascii=False, indent=2)

            with open("data/snapshot.html", "w", encoding="utf-8") as snap:
                snap.write(page.content())

            print(f"\n✅ Total unique: {len(all_tournaments)} tournois")
            print("📁 Résultats : data/tournaments.json")
            print("🧾 Snapshot : data/snapshot.html")

            if os.path.exists("data/app.db"):
                print("⚠️ La base SQLite existe déjà. Si une erreur NOT NULL persiste, supprimez-la :")
                print("   rm -f data/app.db  (elle sera régénérée ensuite)")

        finally:
            browser.close()

    try:
        with open(Path(OUTPUT_FILE), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload:
            _upsert_database(payload)
            print("🗄️  Base SQLite mise à jour : data/app.db")
    except Exception as exc:  # pragma: no cover - best effort
        print(f"⚠️  Impossible de mettre à jour la base SQLite: {exc}", file=sys.stderr)


if __name__ == "__main__":
    manual_scrape()
