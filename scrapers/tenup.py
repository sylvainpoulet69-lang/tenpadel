"""Playwright helpers encapsulating TenUp UI interactions."""
from __future__ import annotations

import random
import re
import time

from playwright.sync_api import Page


def _pause() -> None:
    """Sleep a short random delay to avoid hammering the UI."""

    time.sleep(random.uniform(1.1, 2.0))


def _click(locator, attempts: int = 3, timeout: float = 8000) -> None:
    """Click a locator with retries to mitigate flaky UI behaviour."""

    for attempt in range(attempts):
        try:
            locator.wait_for(state="visible", timeout=timeout)
            locator.click()
            _pause()
            return
        except Exception:
            if attempt == attempts - 1:
                raise
            _pause()


def accept_cookies(page: Page) -> None:
    """Accept the TenUp cookie banner if it is displayed."""

    try:
        _click(page.get_by_role("button", name="TOUT ACCEPTER"))
    except Exception:
        # Banner may not be shown; ignore.
        pass


def select_ligue_paca_alpes_maritimes(page: Page) -> None:
    """Select the PACA league and Alpes Maritimes committee."""

    _click(page.get_by_text("Ligue", exact=True))
    _click(page.get_by_role("button", name=re.compile(r"Dans quelle ligue voulez-vous", re.I)))
    _click(page.get_by_text("PROVENCE ALPES COTE D'AZUR", exact=True))
    _click(page.get_by_role("link", name="SUIVANT"))
    _click(page.get_by_role("button", name="ALPES MARITIMES"))
    _click(page.get_by_role("link", name="VALIDER"))


def select_discipline_padel(page: Page) -> None:
    """Switch the search discipline to padel."""

    _click(page.get_by_role("heading", name="Tennis"))
    _click(page.get_by_text("Padel", exact=True))
    _click(page.get_by_text("Padel", exact=True))
    _click(page.get_by_role("button", name=re.compile(r"Appliquer", re.I)))


def apply_sort_by_start_date(page: Page) -> None:
    """Try to sort results by start date; fallback is handled client-side."""

    try:
        page.get_by_role("combobox").select_option("dateDebut asc")
        _pause()
    except Exception:
        print("WARNING: Tri UI indisponible; tri côté code.")


def navigate_to_results(page: Page) -> None:
    """Wait for the TenUp results view to be fully loaded."""

    page.wait_for_load_state("networkidle")


__all__ = [
    "accept_cookies",
    "select_ligue_paca_alpes_maritimes",
    "select_discipline_padel",
    "apply_sort_by_start_date",
    "navigate_to_results",
]
