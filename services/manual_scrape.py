"""Semi-automatic TenUp scraper driven by a human applying filters."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from scrapers.tenup import extract_current_page_items, try_click_next
from services.db_import import import_items

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
OUT_JSON = DATA / "tournaments.json"
SNAPSHOT = DATA / "snapshot.html"

SEARCH_URL = "https://tenup.fft.fr/recherche/tournois"


def normalize_item(it: dict) -> dict:
    """Ensure minimal default values for tournaments."""

    it = dict(it)
    it["name"] = (it.get("name") or it.get("title") or "Tournoi").strip()
    return it


def is_valid(it: dict) -> bool:
    """Only keep tournaments exposing a detail_url."""

    return bool(it.get("detail_url"))


def main() -> None:
    """Open a browser, wait for filters, then scrape paginated results."""

    print("=== SCRAPER LES TOURNOIS PADEL (mode semi-auto) ===")
    print("1) Un Chromium va s’ouvrir.")
    print("2) Connecte-toi si besoin, applique TES FILTRES (PADEL uniquement).")
    print("3) Quand la page de résultats est visible et filtrée, reviens ici et appuie sur Entrée.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context()
        page = context.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded")

        input("Appuie sur Entrée pour démarrer le scraping de la page courante… ")

        all_items: list[dict] = []
        seen: set[str] = set()

        # Page 1
        cur = [normalize_item(x) for x in extract_current_page_items(page)]
        cur_valid = [x for x in cur if is_valid(x)]
        for it in cur_valid:
            u = it["detail_url"]
            if u in seen:
                continue
            seen.add(u)
            all_items.append(it)
        print(f">> Page 1 : +{len(cur_valid)} (total {len(all_items)})")

        # Pagination
        page_idx = 1
        while True:
            ok = try_click_next(page)
            if not ok:
                break
            page_idx += 1
            page.wait_for_timeout(500)
            cur = [normalize_item(x) for x in extract_current_page_items(page)]
            cur_valid = [x for x in cur if is_valid(x)]
            added = 0
            for it in cur_valid:
                u = it["detail_url"]
                if u in seen:
                    continue
                seen.add(u)
                all_items.append(it)
                added += 1
            print(f">> Page {page_idx} : +{added} (total {len(all_items)})")
            if page_idx > 50:
                print("Stop pagination (sécurité)")
                break

        payload = {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": "tenup_playwright_paginated_semi_auto",
            "tournaments": all_items,
        }
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        SNAPSHOT.write_text(page.content(), encoding="utf-8")

        inserted = import_items(all_items)
        print(f"🗃  Import DB: +{inserted} nouvelles lignes (idempotent)")
        print("✅ Fin du workflow: scrape → JSON/snapshot → DB (auto)")

        context.close()
        browser.close()

    print(f"✅ Total unique: {len(all_items)} — écrit: {OUT_JSON}")
    print(f"🖼  Snapshot: {SNAPSHOT}")


if __name__ == "__main__":
    main()
