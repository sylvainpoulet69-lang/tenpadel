"""Playwright helpers dedicated to the TenUp tournament search UI."""
from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

from playwright.sync_api import Locator, Page, expect

LOGGER = logging.getLogger("scrapers.tenup")
TENUP_URL = "https://tenup.fft.fr/recherche/tournois"


def _pause() -> None:
    """Sleep a short, slightly random delay to mimic human interaction."""

    time.sleep(random.uniform(1.2, 2.2))


def click_retry(locator: Locator, attempts: int = 3, timeout: float = 8000) -> None:
    """Click a locator with retries in case the UI is lagging."""

    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            locator.wait_for(state="visible", timeout=timeout)
            locator.click()
            _pause()
            return
        except Exception as exc:  # pragma: no cover - defensive against flaky UI
            last_error = exc
            if attempt == attempts - 1:
                raise
            _pause()
    if last_error:  # pragma: no cover - diagnostic help
        raise last_error


def accept_cookies(page: Page) -> None:
    """Dismiss the cookie banner if it shows up."""

    try:
        banner = page.get_by_role("button", name=re.compile("accepter", re.I))
        if banner.count():
            banner.first.click()
            _pause()
    except Exception:  # pragma: no cover - banner might not exist
        return


def _pattern_from_text(value: str) -> re.Pattern[str]:
    """Build a lenient regex that tolerates accents and spacing variations."""

    pieces: List[str] = []
    for char in value.strip():
        if char.isspace():
            pieces.append(r"\s+")
            continue
        if char in {"'", "\"", "`", "’"}:
            pieces.append("[’'`\"]?")
            continue
        pieces.append(re.escape(char))
    pattern = "".join(pieces)
    if not pattern:
        pattern = ".*"
    return re.compile(pattern, re.I)


def select_ligue_paca_alpes_maritimes(
    page: Page,
    region: str = "PROVENCE ALPES COTE D’AZUR",
    committee: str = "ALPES MARITIMES",
    logger: Optional[logging.Logger] = None,
) -> None:
    """Navigate through the Ligue/Comité selector with robust locators."""

    log = logger or LOGGER
    log.info("Selecting Ligue %s", region)
    click_retry(page.get_by_role("tab", name=re.compile(r"^Ligue$", re.I)))

    button = page.get_by_role("button", name=re.compile(r"ligue.*joue", re.I))
    if not button.count():
        button = page.get_by_placeholder(re.compile(r"ligue", re.I)).first
    click_retry(button)

    region_pattern = _pattern_from_text(region)
    click_retry(page.get_by_role("checkbox", name=region_pattern))
    click_retry(page.get_by_role("button", name=re.compile(r"^SUIVANT$", re.I)))

    log.info("Selecting Comité %s", committee)
    committee_pattern = _pattern_from_text(committee)
    click_retry(page.get_by_role("button", name=committee_pattern))
    click_retry(page.get_by_role("button", name=re.compile(r"^VALIDER$", re.I)))


def select_discipline_padel(page: Page, logger: Optional[logging.Logger] = None) -> None:
    """Switch the discipline from Tennis to Padel via the popover menu."""

    log = logger or LOGGER
    log.info("Selecting Padel discipline")
    click_retry(page.get_by_role("button", name=re.compile(r"^Tennis$", re.I)))
    click_retry(page.get_by_role("button", name=re.compile(r"^Padel$", re.I)))
    click_retry(page.get_by_role("button", name=re.compile(r"^APPLIQUER$", re.I)))


def search_and_sort(page: Page, logger: Optional[logging.Logger] = None) -> None:
    """Trigger the search and try to sort the result list by start date."""

    log = logger or LOGGER
    log.info("Launching search")
    click_retry(page.get_by_role("button", name=re.compile(r"^RECHERCHER$", re.I)))
    page.wait_for_load_state("networkidle")

    try:
        tri_trigger = page.get_by_text(re.compile(r"^Tri par ", re.I)).first
        click_retry(tri_trigger)
        click_retry(page.get_by_role("menuitem", name=re.compile(r"date de début", re.I)))
    except Exception:
        log.warning("Sort by start date failed; will sort client-side.")
    else:
        try:
            expect(page.get_by_text(re.compile(r"date de début", re.I))).to_be_visible(timeout=8000)
        except Exception:  # pragma: no cover - best effort expectation
            pass


WARNING_MESSAGE = "WARNING Using client-side date filter."


def warn_client_side_date_filter(logger: Optional[logging.Logger] = None) -> None:
    """Log the warning about bypassing the TenUp date picker."""

    log = logger or LOGGER
    log.warning(WARNING_MESSAGE)


FR_MONTHS = {
    "janv": 1,
    "jan.": 1,
    "févr": 2,
    "fév.": 2,
    "fevr": 2,
    "mars": 3,
    "avr.": 4,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7,
    "juil.": 7,
    "août": 8,
    "aout": 8,
    "sept": 9,
    "sep.": 9,
    "oct": 10,
    "oct.": 10,
    "nov": 11,
    "déc": 12,
    "déc.": 12,
    "dec": 12,
    "dec.": 12,
}


def _date_fr_to_iso(value: str) -> Optional[str]:
    match = re.search(r"(\d{1,2})\s+([a-zéû\.]+)\s+(\d{4})", value.lower())
    if not match:
        return None
    day = int(match.group(1))
    month_token = match.group(2).replace("é", "e").replace("û", "u")
    month = FR_MONTHS.get(month_token, None)
    if not month:
        return None
    year = int(match.group(3))
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:  # pragma: no cover - guard against invalid dates
        return None


def extract_cards(page: Page, limit: int = 500) -> List[Dict[str, Optional[str]]]:
    """Scroll through the TenUp results and normalise the visible cards."""

    items: List[Dict[str, Optional[str]]] = []
    seen = -1
    while len(items) < limit and len(items) != seen:
        seen = len(items)
        cards = page.locator(
            "article, div[data-testid='event-card'], li:has(div:has-text('DM')), div:has-text('DM /')"
        ).all()
        for card in cards:
            if len(items) >= limit:
                break
            try:
                text = card.inner_text()
            except Exception:  # pragma: no cover - skip faulty cards
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
            start_iso = _date_fr_to_iso(raw_dates[0]) if raw_dates else None
            end_iso = _date_fr_to_iso(raw_dates[1]) if len(raw_dates) > 1 else start_iso

            level_match = re.search(r"\bP(100|250|500|1000|1500|2000)\b", text)
            category_match = re.search(r"\bDM(?:\s*/\s*DX)?|\bSM\s*/\s*SD|\bDX\b", text, re.I)
            level = level_match.group(0) if level_match else None
            category = (
                category_match.group(0).upper().replace(" ", "") if category_match else None
            )

            location_line = ""
            for line in text.splitlines():
                if "," in line:
                    location_line = line.strip()
                    break
            club_name: Optional[str] = None
            city: Optional[str] = None
            if location_line:
                parts = [segment.strip() for segment in location_line.split(",")]
                if len(parts) > 1:
                    club_name = ", ".join(parts[:-1])
                    city = parts[-1]
                else:
                    club_name = parts[0]
                    city = None

            tournament_id = re.sub(
                r"\W+", "-", f"{name}-{start_iso or ''}-{end_iso or ''}"
            ).strip("-").lower()
            if not tournament_id:
                continue

            items.append(
                {
                    "tournament_id": tournament_id,
                    "name": name,
                    "level": level,
                    "category": category,
                    "club_name": club_name,
                    "city": city,
                    "start_date": start_iso,
                    "end_date": end_iso,
                    "detail_url": None,
                    "registration_url": None,
                }
            )
        page.mouse.wheel(0, 2200)
        _pause()
    return items[:limit]


__all__ = [
    "TENUP_URL",
    "accept_cookies",
    "click_retry",
    "extract_cards",
    "search_and_sort",
    "select_discipline_padel",
    "select_ligue_paca_alpes_maritimes",
    "warn_client_side_date_filter",
]
