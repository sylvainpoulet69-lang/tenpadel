"""Playwright helpers encapsulating TenUp UI interactions."""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Callable, Iterable

from playwright.sync_api import Locator, Page

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


def _pause() -> None:
    """Sleep a short random delay to avoid hammering the UI."""

    time.sleep(random.uniform(0.8, 1.4))


def _as_iterable(obj: Iterable | Locator | Callable[[Page], Locator]):
    if isinstance(obj, (list, tuple, set)):
        return list(obj)
    return [obj]


def _describe_locator(candidate) -> str:
    if callable(candidate):
        return getattr(candidate, "__name__", repr(candidate))
    return getattr(candidate, "_selector", repr(candidate))


def _try_click(
    page: Page,
    candidates: Iterable[Locator | Callable[[Page], Locator]],
    label: str,
    *,
    timeout: float = 12000,
    debug: bool = False,
) -> bool:
    """Attempt to click several locators while swallowing failures."""

    last_error: Exception | None = None
    for cand in _as_iterable(candidates):
        try:
            locator = cand(page) if callable(cand) else cand
        except Exception as exc:  # pragma: no cover - defensive
            last_error = exc
            continue

        try:
            count = locator.count()
        except Exception:
            count = -1
        if count == 0:
            if debug:
                LOGGER.debug("[DEBUG] '%s' indisponible via %s", label, _describe_locator(cand))
            continue

        try:
            locator.scroll_into_view_if_needed(timeout=timeout)
        except Exception as exc:
            if debug:
                LOGGER.debug("[DEBUG] scroll raté pour %s: %s", label, exc)
        try:
            locator.wait_for(state="visible", timeout=timeout)
        except Exception as exc:
            last_error = exc
            continue
        try:
            locator.click(timeout=timeout)
            _pause()
            if debug:
                LOGGER.debug("[DEBUG] '%s' cliqué", label)
            return True
        except Exception as exc:
            last_error = exc
            if debug:
                LOGGER.debug("[DEBUG] clic échoué pour %s: %s", label, exc)
    if last_error:
        LOGGER.warning("[WARN] impossible de cliquer sur %s: %s", label, last_error)
    else:
        LOGGER.warning("[WARN] aucun sélecteur valide pour %s", label)
    return False


def accept_cookies(page: Page, *, debug: bool = False) -> None:
    """Accept the TenUp cookie banner if it is displayed."""

    _try_click(
        page,
        [
            lambda p: p.get_by_role("button", name=re.compile(r"TOUT ACCEPTER", re.I)),
            lambda p: p.locator("button:has-text('TOUT ACCEPTER')"),
            lambda p: p.get_by_role("button", name=re.compile(r"ACCEPTER", re.I)),
        ],
        "bandeau cookies",
        debug=debug,
    )


def select_discipline_padel(page: Page, *, debug: bool = False) -> None:
    """Switch the search discipline to padel with robust fallbacks."""

    page.wait_for_timeout(1500)

    sidebar_clicked = _try_click(
        page,
        [
            lambda p: p.locator("aside").get_by_role(
                "button", name=re.compile(r"^\s*Padel\s*$", re.I)
            ),
            lambda p: p.locator("aside button:has-text('Padel')"),
            lambda p: p.locator("aside [role='button']:has-text('Padel')"),
            lambda p: p.locator("aside").get_by_text("Padel", exact=True),
        ],
        "Padel (sidebar)",
        debug=debug,
    )

    padel_selected = sidebar_clicked

    if not padel_selected:
        opened = _try_click(
            page,
            [
                lambda p: p.get_by_role("button", name=re.compile(r"^\s*Tennis\s*$", re.I)),
                lambda p: p.locator("button:has-text('Tennis')"),
                lambda p: p.locator("div[role='button']:has-text('Tennis')"),
                lambda p: p.locator("div:has-text('Tennis')").locator(
                    "xpath=ancestor-or-self::button[1]"
                ),
                lambda p: p.get_by_text("Tennis", exact=True),
            ],
            "ouvrir les disciplines",
            debug=debug,
        )
        if opened:
            page.wait_for_timeout(500)
            padel_selected = _try_click(
                page,
                [
                    lambda p: p.get_by_text("Padel", exact=True),
                    lambda p: p.locator("button:has-text('Padel')"),
                    lambda p: p.locator("[role='option']:has-text('Padel')"),
                    lambda p: p.locator("div:has-text('Padel')"),
                ],
                "Padel (menu)",
                debug=debug,
            )

    if not padel_selected:
        containers = [
            "#epreuves-checkboxes-replace",
            "#type-container-replace",
            "#categorie-tournoi-container-replace",
        ]
        for cid in containers:
            root = page.locator(cid)
            if root.count() == 0:
                continue
            if _try_click(
                page,
                [
                    lambda _p, r=root: r.get_by_text("Padel", exact=True),
                    lambda _p, r=root: r.locator("label:has-text('Padel')"),
                    lambda _p, r=root: r.locator("button:has-text('Padel')"),
                ],
                f"Padel ({cid})",
                debug=debug,
            ):
                padel_selected = True
                break

    if padel_selected:
        LOGGER.info("[INFO] Discipline Padel sélectionnée.")
    else:
        LOGGER.warning("[WARN] Impossible de forcer 'Padel' — poursuite du scraping.")

    page.wait_for_timeout(400)
    _try_click(
        page,
        [
            lambda p: p.get_by_role("button", name=re.compile(r"Appliquer", re.I)),
            lambda p: p.locator("button:has-text('APPLIQUER')"),
            lambda p: p.locator("aside").get_by_role(
                "button", name=re.compile(r"Appliquer", re.I)
            ),
        ],
        "Appliquer",
        debug=debug,
    )
    page.wait_for_timeout(400)
    _try_click(
        page,
        [
            lambda p: p.get_by_role("button", name=re.compile(r"RECHERCHER", re.I)),
            lambda p: p.locator("aside button:has-text('RECHERCHER')"),
            lambda p: p.locator("button:has-text('Rechercher')"),
        ],
        "Rechercher",
        debug=debug,
    )
    page.wait_for_timeout(2000)


def _scroll_to_load(page: Page, attempts: int = 14, *, debug: bool = False) -> None:
    """Scroll down progressively to trigger lazy loading of tournaments."""

    last_count = -1
    stagnant = 0
    for idx in range(attempts):
        page.mouse.wheel(0, 2400)
        wait_ms = random.uniform(450, 900)
        page.wait_for_timeout(int(wait_ms))
        try:
            current = page.locator("div.card-event, div[data-testid='event-card'], article").count()
        except Exception:
            current = -1
        if debug:
            LOGGER.debug(
                "[DEBUG] Scroll %s/%s – cartes visibles: %s",
                idx + 1,
                attempts,
                current if current >= 0 else "?",
            )
        if current == last_count and current != -1:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
        last_count = current


def navigate_to_results(page: Page) -> None:
    """Wait for the TenUp results view to be fully loaded."""

    page.wait_for_load_state("networkidle")


__all__ = [
    "accept_cookies",
    "select_discipline_padel",
    "navigate_to_results",
    "_scroll_to_load",
    "extract_current_page_items",
    "try_click_next",
]

RE_CAT = re.compile(r"\bP(?:25|50|100|250|500|1000|2000)\b", re.I)


def _closest_text(page: Page, handle):
    try:
        return page.evaluate("(el)=> (el.closest('article,div,li')||el).innerText", handle)
    except Exception:
        return ""


def extract_current_page_items(page: Page):
    anchors = page.locator("a[href*='/tournoi/']")
    n = anchors.count()
    items = []
    for i in range(n):
        try:
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""
            if not href:
                continue
            if href.startswith("/"):
                href = "https://tenup.fft.fr" + href

            title = (a.inner_text() or "").strip()
            ctx = _closest_text(page, a.element_handle()) or ""
            ctx = ctx.replace("\xa0", " ").strip()

            mcat = RE_CAT.search(title) or RE_CAT.search(ctx)
            category = mcat.group(0).upper() if mcat else None

            club = None
            if " - " in title:
                parts = [p.strip() for p in title.split(" - ") if p.strip()]
                if len(parts) >= 2:
                    club = parts[-1]

            item = {
                "name": title or "Tournoi",
                "level": None,
                "category": category,
                "club_name": club,
                "city": None,
                "start_date": None,
                "end_date": None,
                "detail_url": href,
                "registration_url": None,
                "title": title,
                "url": href,
                "sex": None,
            }
            items.append(item)
        except Exception:
            continue

    seen, out = set(), []
    for it in items:
        u = it.get("detail_url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


def try_click_next(page: Page):
    try:
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(200)
    except Exception:
        pass

    for role, name in [
        ("button", r"(Suivant|Page suivante|Next|>|\u203A)"),
        ("link", r"(Suivant|Page suivante|Next|>|\u203A)"),
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
