"""TenUp padel tournaments scraper using Playwright.

This script navigates through the paginated TenUp search results, extracts
structured information about each tournament card and writes a consolidated
`tournaments.json` file as well as a HTML snapshot for auditing purposes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

CONFIG_PATH = Path("config.json")
DEFAULT_SOURCE = "tenup_scrape_playwright_paged"
TENUP_BASE_URL = "https://tenup.fft.fr"

logger = logging.getLogger("fetch_auto")


@dataclass
class RawTournament:
    """Lightweight representation extracted from the DOM."""

    href: str
    title: str
    date_text: Optional[str]
    container_text: str
    badge_texts: List[str]


@dataclass
class Tournament:
    """Structured tournament entry ready to be serialised to JSON."""

    tournament_id: str
    date: Optional[str]
    date_text: Optional[str]
    title: str
    club: Optional[str]
    city: Optional[str]
    url: str
    category: Optional[str]
    sex: Optional[str]

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "tournament_id": self.tournament_id,
            "date": self.date,
            "date_text": self.date_text,
            "title": self.title,
            "club": self.club,
            "city": self.city,
            "url": self.url,
            "category": self.category,
            "sex": self.sex,
        }


MONTHS_FR = {
    "janv": 1,
    "janvier": 1,
    "févr": 2,
    "fevr": 2,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avr": 4,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "sept": 9,
    "septembre": 9,
    "oct": 10,
    "octobre": 10,
    "nov": 11,
    "novembre": 11,
    "déc": 12,
    "dec": 12,
    "décembre": 12,
    "decembre": 12,
}

SEX_KEYWORDS = {
    "DM": "DM",
    "DD": "DD",
    "DX": "DX",
    "HOMMES": "DM",
    "HOMME": "DM",
    "MASC": "DM",
    "DAM": "DD",
    "FEMME": "DD",
    "MIXTE": "DX",
}

CATEGORY_PATTERN = re.compile(r"\bP(?:25|50|100|250|500|1000|2000)\b", re.IGNORECASE)
SEX_PATTERN = re.compile(r"\b(DM|DD|DX)\b", re.IGNORECASE)


def load_config() -> Dict[str, object]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Configuration file {CONFIG_PATH} not found")
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_parent_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def make_absolute_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        # Unexpected relative path – normalise by ensuring leading slash.
        url = "/" + url
    return f"{TENUP_BASE_URL}{url}"


def compute_tournament_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def parse_date(date_text: Optional[str]) -> Optional[str]:
    if not date_text:
        return None
    text = date_text.strip().lower()
    # Normalise unicode apostrophes etc.
    text = text.replace("'", " ").replace("\u2019", " ")
    # Replace double spaces
    text = re.sub(r"\s+", " ", text)

    match = re.search(r"(\d{1,2})\s*([a-zéû\.]+)\s*(\d{4})?", text)
    if not match:
        return None
    day = int(match.group(1))
    month_token = match.group(2).strip(". ")
    year_token = match.group(3)
    month = MONTHS_FR.get(month_token)
    if not month:
        return None
    year = int(year_token) if year_token else datetime.utcnow().year
    try:
        date_obj = datetime(year, month, day)
    except ValueError:
        return None
    return date_obj.strftime("%Y-%m-%d")


def parse_sex(raw: RawTournament) -> Optional[str]:
    texts = raw.badge_texts + [raw.container_text, raw.title]
    for text in texts:
        if not text:
            continue
        for match in SEX_PATTERN.findall(text):
            return match.upper()
        upper_text = text.upper()
        for keyword, code in SEX_KEYWORDS.items():
            if keyword in upper_text:
                return code
    return None


def parse_category(raw: RawTournament) -> Optional[str]:
    if raw.badge_texts:
        for badge in raw.badge_texts:
            match = CATEGORY_PATTERN.search(badge)
            if match:
                return match.group(0).upper()
    match = CATEGORY_PATTERN.search(raw.container_text)
    if match:
        return match.group(0).upper()
    return None


def parse_club_and_city(raw: RawTournament) -> (Optional[str], Optional[str]):
    # Heuristic: take lines after the title that don't look like category/date/sex.
    excluded_patterns = (
        CATEGORY_PATTERN,
        SEX_PATTERN,
        re.compile(r"\b(MIXTE|HOMMES?|DAMES?)\b", re.IGNORECASE),
    )
    lines = [line.strip() for line in raw.container_text.splitlines() if line.strip()]
    title_upper = raw.title.strip().upper()
    candidates: List[str] = []
    for line in lines:
        if line.strip().upper() == title_upper:
            continue
        skip = False
        for pattern in excluded_patterns:
            if pattern.search(line):
                skip = True
                break
        if skip:
            continue
        if re.search(r"\b\d{1,2}\b", line) and any(month in line.lower() for month in MONTHS_FR.keys()):
            # Likely date
            continue
        candidates.append(line)
    club = candidates[0] if candidates else None
    city = candidates[1] if len(candidates) > 1 else None
    return club, city


def collect_raw_tournaments(page: Page) -> List[RawTournament]:
    logger.debug("Extracting tournaments from current page")
    cards: List[RawTournament] = []
    elements = page.evaluate(
        """
        () => {
            const seen = new Set();
            const data = [];
            const anchors = document.querySelectorAll('a[href*="/tournoi/"]');
            anchors.forEach(anchor => {
                const href = anchor.getAttribute('href');
                if (!href || seen.has(href)) {
                    return;
                }
                seen.add(href);
                const container = anchor.closest('article, li, .card, .MuiCard-root, .result-card, .v-card, .search-card') || anchor.parentElement;
                const badgeSelectors = ['[class*="Chip"]', '[class*="Tag"]', '.badge', '.chip', '.label'];
                const badges = [];
                if (container) {
                    badgeSelectors.forEach(selector => {
                        container.querySelectorAll(selector).forEach(node => {
                            const text = (node.textContent || '').trim();
                            if (text) {
                                badges.push(text);
                            }
                        });
                    });
                }
                let title = anchor.textContent ? anchor.textContent.trim() : '';
                if ((!title || title.length < 4) && container) {
                    const heading = container.querySelector('h1, h2, h3, h4, .title, .card-title');
                    if (heading && heading.textContent) {
                        title = heading.textContent.trim();
                    }
                }
                let dateText = null;
                if (container) {
                    const dateNode = container.querySelector('time, [class*="date"], .result-date');
                    if (dateNode && dateNode.textContent) {
                        dateText = dateNode.textContent.trim();
                    }
                }
                const containerText = container && container.innerText ? container.innerText : (anchor.innerText || '');
                data.push({
                    href,
                    title,
                    date_text: dateText,
                    container_text: containerText,
                    badge_texts: badges,
                });
            });
            return data;
        }
        """
    )
    for item in elements:
        cards.append(
            RawTournament(
                href=item.get("href", ""),
                title=item.get("title", "").strip(),
                date_text=(item.get("date_text") or None),
                container_text=item.get("container_text", ""),
                badge_texts=item.get("badge_texts", []) or [],
            )
        )
    return cards


def auto_scroll(page: Page, *, pause_ms: int, max_loops: int) -> None:
    for iteration in range(max_loops):
        previous_height = page.evaluate("() => document.body.scrollHeight")
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        logger.debug("Auto-scroll iteration %s", iteration + 1)
        time.sleep(pause_ms / 1000)
        current_height = page.evaluate("() => document.body.scrollHeight")
        if current_height == previous_height:
            break


def go_to_next_page(page: Page) -> bool:
    strategies = [
        {"description": "aria-label next", "type": "locator", "value": "[aria-label='Suivant'], [aria-label='Next']"},
        {"description": "rel next", "type": "locator", "value": "a[rel='next']"},
        {"description": "text suivant", "type": "text", "value": "Suivant"},
        {"description": "text suivant arrow", "type": "text", "value": "Suivant ›"},
        {"description": "role button", "type": "role", "value": {"name": re.compile("Suivant", re.IGNORECASE)}},
    ]
    for strategy in strategies:
        try:
            if strategy["type"] == "locator":
                locator = page.locator(strategy["value"])
            elif strategy["type"] == "text":
                locator = page.get_by_text(strategy["value"], exact=False)
            elif strategy["type"] == "role":
                locator = page.get_by_role("button", **strategy["value"])
            else:
                continue
            if locator.count() == 0:
                continue
            logger.debug("Trying pagination via %s", strategy["description"])
            locator.first.click()
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                logger.debug("Timeout waiting for network idle after pagination")
            return True
        except PlaywrightTimeoutError:
            continue
        except Exception as exc:  # noqa: BLE001
            logger.debug("Pagination strategy %s failed: %s", strategy["description"], exc)
            continue
    # Fallback: try JS click on arrow glyph
    fallback_script = """
        () => {
            const candidates = Array.from(document.querySelectorAll('a, button'));
            const target = candidates.find(node => node.textContent && node.textContent.trim().startsWith('Suivant'));
            if (target) {
                target.click();
                return true;
            }
            return false;
        }
    """
    try:
        clicked = page.evaluate(fallback_script)
        if clicked:
            logger.debug("Fallback JS pagination succeeded")
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                pass
            return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("Fallback pagination failed: %s", exc)
    return False


def serialise_tournaments(tournaments: Iterable[Tournament], path: Path) -> None:
    data = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "source": DEFAULT_SOURCE,
        "tournaments": [tournament.to_dict() for tournament in tournaments],
    }
    ensure_parent_directory(path)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def save_snapshot(page: Page, path: Path) -> None:
    ensure_parent_directory(path)
    html = page.content()
    with path.open("w", encoding="utf-8") as fh:
        fh.write(html)


def save_storage_state(context: BrowserContext, path: Path) -> None:
    ensure_parent_directory(path)
    context.storage_state(path=path)


def build_tournament(raw: RawTournament) -> Tournament:
    absolute_url = make_absolute_url(raw.href)
    tournament_id = compute_tournament_id(absolute_url)
    sex = parse_sex(raw)
    category = parse_category(raw)
    club, city = parse_club_and_city(raw)
    iso_date = parse_date(raw.date_text)
    return Tournament(
        tournament_id=tournament_id,
        date=iso_date,
        date_text=raw.date_text.strip() if raw.date_text else None,
        title=raw.title,
        club=club,
        city=city,
        url=absolute_url,
        category=category,
        sex=sex,
    )


def scrape() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    config = load_config()
    scraper_conf = config.get("tenup", {})
    start_url = scraper_conf.get("start_url")
    if not start_url:
        raise ValueError("Missing 'tenup.start_url' in config.json")

    tournaments_path = Path(scraper_conf.get("tournaments_path", "data/tournaments.json"))
    snapshot_path = Path(scraper_conf.get("snapshot_path", "data/snapshot.html"))
    storage_state_path = Path(scraper_conf.get("storage_state_path", "data/storage_state.json"))

    auto_scroll_enabled = bool(scraper_conf.get("auto_scroll", True))
    max_scroll_loops = int(scraper_conf.get("max_scroll_loops", 15))
    scroll_pause_ms = int(scraper_conf.get("scroll_pause_ms", 400))
    save_snapshot_enabled = bool(scraper_conf.get("save_snapshot_html", True))

    headless = bool(scraper_conf.get("headless", True))
    slow_mo_ms = int(scraper_conf.get("slow_mo_ms", 0))

    logger.info("Launching Playwright (headless=%s)", headless)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo_ms or None)
        context_kwargs: Dict[str, object] = {}
        if storage_state_path.exists():
            context_kwargs["storage_state"] = str(storage_state_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        logger.info("Navigating to %s", start_url)
        page.goto(start_url, wait_until="networkidle")

        all_tournaments: Dict[str, Tournament] = {}
        page_index = 1

        while True:
            logger.info("Processing page %s", page_index)
            if auto_scroll_enabled:
                auto_scroll(page, pause_ms=scroll_pause_ms, max_loops=max_scroll_loops)
            raw_items = collect_raw_tournaments(page)
            logger.info("Found %s raw tournaments on page %s", len(raw_items), page_index)
            for raw in raw_items:
                tournament = build_tournament(raw)
                if tournament.tournament_id in all_tournaments:
                    continue
                all_tournaments[tournament.tournament_id] = tournament
            logger.info("Total unique tournaments so far: %s", len(all_tournaments))

            if not go_to_next_page(page):
                logger.info("No further pages detected; stopping pagination")
                break
            page_index += 1

        serialise_tournaments(all_tournaments.values(), tournaments_path)
        logger.info("Wrote tournaments JSON to %s", tournaments_path)

        if save_snapshot_enabled:
            save_snapshot(page, snapshot_path)
            logger.info("Saved HTML snapshot to %s", snapshot_path)

        save_storage_state(context, storage_state_path)
        logger.info("Stored session state to %s", storage_state_path)

        context.close()
        browser.close()


if __name__ == "__main__":
    try:
        scrape()
    except KeyboardInterrupt:
        sys.exit(1)
