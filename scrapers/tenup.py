"""Playwright helpers encapsulating TenUp UI interactions."""
from __future__ import annotations

import random
import re
import time

from playwright.sync_api import Page


def _pause() -> None:
    """Sleep a short random delay to avoid hammering the UI."""

    time.sleep(random.uniform(1.0, 1.8))


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


def select_discipline_padel(page: Page) -> None:
    """Switch the search discipline to padel."""

    _click(page.get_by_role("heading", name="Tennis"))
    _click(page.get_by_text("Padel", exact=True))
    _click(page.get_by_role("button", name=re.compile(r"Appliquer", re.I)))


def navigate_to_results(page: Page) -> None:
    """Wait for the TenUp results view to be fully loaded."""

    page.wait_for_load_state("networkidle")


__all__ = [
    "accept_cookies",
    "select_discipline_padel",
    "navigate_to_results",
]
