import json, re, datetime, sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
OUT_JSON = DATA / "tournaments.json"
SNAPSHOT = DATA / "snapshot.html"

SEARCH_URL = "https://tenup.fft.fr/recherche/tournois"
HEADLESS = False          # mettre True si tu veux headless
SLOW_MO_MS = 100
SAVE_SNAPSHOT = True

# Mois FR -> mois numérique
MONTH_MAP = {
    'janvier':1, 'janv':1,
    'février':2, 'fevrier':2, 'févr':2, 'fevr':2,
    'mars':3, 'avril':4, 'avr':4, 'mai':5, 'juin':6,
    'juillet':7, 'juil':7, 'août':8, 'aout':8,
    'septembre':9, 'sept':9, 'octobre':10, 'oct':10,
    'novembre':11, 'nov':11, 'décembre':12, 'decembre':12, 'déc':12, 'dec':12
}
RE_DATE = re.compile(
    r"(\d{1,2})\s+(janv\.?|janvier|févr\.?|fevr\.?|février|fevri|mars|avr\.?|avril|mai|juin|juil\.?|juillet|ao[uû]t|sept\.?|septembre|oct\.?|octobre|nov\.?|novembre|d[ée]c\.?|d[ée]cembre)\s+(\d{4})",
    re.I
)
RE_CAT = re.compile(r"\bP(?:25|50|100|250|500|1000|2000)\b", re.I)

def fr_to_iso_any(text: str):
    if not text:
        return None, None
    t = text.lower().replace('\xa0', ' ')
    m = RE_DATE.search(t)
    if not m:
        return None, None
    d = int(m.group(1))
    mo_raw = m.group(2).replace('.', '')
    y = int(m.group(3))
    mo = MONTH_MAP.get(mo_raw, None)
    if not mo:
        return m.group(0), None
    return m.group(0), f"{y:04d}-{mo:02d}-{d:02d}"

def click_cookie_consent(page):
    # essaie plusieurs méthodes pour accepter les cookies
    try:
        btn = page.get_by_role("button", name=re.compile(r"(Tout accepter|Accepter tout|Accepter|J.?accepte)", re.I))
        if btn.count() and btn.first.is_visible():
            btn.first.click(); page.wait_for_timeout(300); return
    except Exception:
        pass
    try:
        css_sel = "#didomi-notice-agree-button, button[aria-label*='accepter' i], .btn-accept, .cc-allow"
        el = page.locator(css_sel)
        if el.count() and el.first.is_visible():
            el.first.click(); page.wait_for_timeout(300); return
    except Exception:
        pass
    try:
        el = page.get_by_text(re.compile(r"(Accepter tout|Tout accepter|Accepter)", re.I), exact=False)
        if el.count() and el.first.is_visible():
            el.first.click(); page.wait_for_timeout(300); return
    except Exception:
        pass

def extract_current_page(page):
    # cible UNIQUEMENT les liens de tournoi
    anchors = page.locator("a[href*='/tournoi/']")
    count = anchors.count()
    items = []
    for i in range(count):
        try:
            a = anchors.nth(i)
            href = a.get_attribute('href') or ""
            if not href:
                continue
            # Texte du conteneur le plus proche (évite le header/footer)
            container_text = page.evaluate(
                "(el) => (el.closest('article,div,li')||el).innerText",
                a.element_handle()
            )
            text = (container_text or "").replace('\xa0', ' ').strip()
            title = (a.inner_text() or "").strip()

            # Catégorie
            mcat = RE_CAT.search(text) or RE_CAT.search(title)
            category = mcat.group(0).upper() if mcat else None

            # Dates (on prend la première date trouvée)
            date_text, date_iso = fr_to_iso_any(text)

            # Club (souvent dans le titre "Nom tournoi - Club")
            club = None
            if " - " in title:
                parts = [p.strip() for p in title.split(" - ") if p.strip()]
                if len(parts) >= 2:
                    club = parts[-1]

            item = {
                # Champs compatibles avec ta DB
                "name": title or "Tournoi",
                "level": None,
                "category": category,
                "club_name": club,
                "city": None,
                "start_date": date_iso,
                "end_date": None,
                "detail_url": href,     # IMPORTANT: pour NOT NULL
                "registration_url": None,

                # Champs utiles côté app web
                "title": title or "Tournoi",
                "date_text": date_text,
                "url": href,            # alias si tu l’utilises côté front
                "sex": None
            }
            items.append(item)
        except Exception:
            continue

    # dédoublonnage par detail_url
    seen, out = set(), []
    for it in items:
        u = it.get("detail_url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out

def try_click_next(page):
    # petit scroll pour faire apparaître la pagination
    try:
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(200)
    except Exception:
        pass

    for role, name in [
        ("button", r"(Suivant|Page suivante|Next|>|\u203A)"),
        ("link",   r"(Suivant|Page suivante|Next|>|\u203A)"),
    ]:
        try:
            el = page.get_by_role(role, name=re.compile(name, re.I))
            if el.count() and el.first.is_enabled():
                el.first.click()
                page.wait_for_load_state('domcontentloaded', timeout=30000)
                return True
        except Exception:
            pass

    for css in ["a[rel='next']", "button[aria-label*='suivant' i]"]:
        try:
            el = page.locator(css)
            if el.count() and el.first.is_enabled():
                el.first.click()
                page.wait_for_load_state('domcontentloaded', timeout=30000)
                return True
        except Exception:
            pass

    return False

def main():
    print("=== SCRAPER LES TOURNOIS PADEL (mode semi-auto) ===")
    print("1) Un Chromium va s’ouvrir.")
    print("2) Connecte-toi si besoin, applique TES FILTRES (PADEL uniquement).")
    print("3) Quand la page de résultats est visible et filtrée, reviens ici et appuie sur Entrée.")
    input("Appuie sur Entrée quand tu es prêt… ")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
        context = browser.new_context()
        page = context.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        click_cookie_consent(page)

        all_items, seen = [], set()

        # 1) Page courante
        page.wait_for_timeout(500)
        cur = extract_current_page(page)
        for it in cur:
            u = it["detail_url"]
            if u in seen: continue
            seen.add(u); all_items.append(it)
        print(f">> Page 1 : {len(cur)} éléments")

        # 2) Pagination
        page_idx = 1
        while True:
            ok = try_click_next(page)
            if not ok:
                break
            page_idx += 1
            page.wait_for_timeout(500)
            cur = extract_current_page(page)
            added = 0
            for it in cur:
                u = it["detail_url"]
                if u in seen: continue
                seen.add(u); all_items.append(it); added += 1
            print(f">> Page {page_idx} : +{added} (total {len(all_items)})")
            # garde-fou si la pagination boucle
            if page_idx > 50:
                print("Stop pagination (sécurité)")
                break

        # 3) Sauvegardes
        payload = {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": "tenup_playwright_paginated",
            "tournaments": all_items
        }
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f">> Total unique: {len(all_items)} — écrit: {OUT_JSON}")

        if SAVE_SNAPSHOT:
            SNAPSHOT.write_text(page.content(), encoding="utf-8")
            print(f">> Snapshot: {SNAPSHOT}")

        context.close(); browser.close()

if __name__ == "__main__":
    main()
