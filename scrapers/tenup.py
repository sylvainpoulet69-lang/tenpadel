"""Playwright-based scraper for TenUp padel tournaments."""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin

import pendulum
from playwright.sync_api import (  # type: ignore[import-untyped]
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class ScrapedTournament:
    """Normalised structure returned by :class:`TenUpScraper`."""

    tournament_id: str
    name: str
    level: Optional[str]
    category: str
    club_name: Optional[str]
    club_code: Optional[str]
    organizer: Optional[str]
    city: Optional[str]
    region: Optional[str]
    address: Optional[str]
    start_date: str
    end_date: str
    registration_deadline: Optional[str]
    surface: Optional[str]
    indoor_outdoor: Optional[str]
    draw_size: Optional[int]
    price: Optional[float]
    status: Optional[str]
    detail_url: str
    registration_url: Optional[str]
    last_scraped_at: str

    def asdict(self) -> Dict[str, object]:
        return {
            "tournament_id": self.tournament_id,
            "name": self.name,
            "level": self.level,
            "category": self.category,
            "club_name": self.club_name,
            "club_code": self.club_code,
            "organizer": self.organizer,
            "city": self.city,
            "region": self.region,
            "address": self.address,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "registration_deadline": self.registration_deadline,
            "surface": self.surface,
            "indoor_outdoor": self.indoor_outdoor,
            "draw_size": self.draw_size,
            "price": self.price,
            "status": self.status,
            "detail_url": self.detail_url,
            "registration_url": self.registration_url,
            "last_scraped_at": self.last_scraped_at,
        }


class TenUpScraper:
    """Scrape the TenUp tournament catalogue via Playwright only."""

    def __init__(
        self,
        *,
        base_url: str,
        headless: bool = True,
        request_timeout_ms: int = 30000,
        respect_rate_limit: bool = True,
        log_path: Optional[Path] = None,
        random_delay_range: tuple[float, float] = (1.2, 2.0),
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url
        self.headless = headless
        self.request_timeout_ms = request_timeout_ms
        self.respect_rate_limit = respect_rate_limit
        self.random_delay_range = random_delay_range
        self.max_retries = max_retries
        self._logger = logging.getLogger("scrapers.tenup")
        self._log_path = Path(log_path) if log_path else None
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(self._log_path, encoding="utf-8")
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            handler.setFormatter(formatter)
            if not any(isinstance(h, logging.FileHandler) and h.baseFilename == handler.baseFilename for h in self._logger.handlers):
                self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)
        self._page: Optional[Page] = None
        self._context: Optional[BrowserContext] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def scrape(
        self,
        *,
        region: Optional[str],
        date_from: str,
        date_to: str,
        categories: Iterable[str],
        levels: Sequence[str],
        limit: int,
    ) -> List[ScrapedTournament]:
        """Return a normalised list of tournaments matching the filters."""

        self._logger.info(
            "Starting TenUp scrape",
            extra={
                "region": region,
                "date_from": date_from,
                "date_to": date_to,
                "categories": list(categories),
                "levels": list(levels),
                "limit": limit,
            },
        )
        try:
            with sync_playwright() as playwright:
                browser = self._launch_browser(playwright)
                try:
                    context = self._new_context(browser)
                    self._context = context
                    page = context.new_page()
                    self._page = page
                    tournaments = self._scrape_with_page(
                        page,
                        region=region,
                        date_from=date_from,
                        date_to=date_to,
                        categories=list(categories),
                        levels=list(levels),
                        limit=limit,
                    )
                finally:
                    self._page = None
                    if self._context is not None:
                        self._context.close()
                        self._context = None
                    browser.close()
        except Exception:
            self._capture_debug_artifacts()
            raise

        deduped: Dict[str, ScrapedTournament] = {}
        for item in tournaments:
            deduped[item.tournament_id] = item
        sorted_items = sorted(deduped.values(), key=lambda item: item.start_date or "")
        self._logger.info("Scrape completed", extra={"count": len(sorted_items)})
        return sorted_items[:limit]

    # ------------------------------------------------------------------
    # Browser helpers
    # ------------------------------------------------------------------
    def _launch_browser(self, playwright) -> Browser:
        return playwright.chromium.launch(headless=self.headless)

    def _new_context(self, browser: Browser) -> BrowserContext:
        context = browser.new_context(
            locale="fr-FR",
            timezone_id="Europe/Paris",
            user_agent=_USER_AGENT,
            viewport={"width": 1440, "height": 900},
        )
        return context

    def _scrape_with_page(
        self,
        page: Page,
        *,
        region: Optional[str],
        date_from: str,
        date_to: str,
        categories: Sequence[str],
        levels: Sequence[str],
        limit: int,
    ) -> List[ScrapedTournament]:
        self._goto_home(page)
        self._accept_cookies(page)
        self._apply_filters(page, region=region, date_from=date_from, date_to=date_to, levels=levels)

        tournaments: List[ScrapedTournament] = []
        seen_urls: set[str] = set()
        for category in [token.upper() for token in (categories or ("MIXTE",))]:
            self._select_category(page, category)
            self._refresh_results(page)
            items = self._collect_list_items(page, limit)
            for summary in items:
                if summary.detail_url in seen_urls:
                    continue
                seen_urls.add(summary.detail_url)
                tournaments.append(summary)
                if len(tournaments) >= limit:
                    break
            if len(tournaments) >= limit:
                break
        return tournaments

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------
    def _goto_home(self, page: Page) -> None:
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=self.request_timeout_ms)
        page.wait_for_load_state("networkidle", timeout=self.request_timeout_ms)

    def _accept_cookies(self, page: Page) -> None:
        try:
            button = page.get_by_role("button", name=re.compile("accepter", re.I))
            if button.is_visible():
                button.click()
                self._rate_limit()
        except PlaywrightError:
            self._logger.debug("Cookie banner not displayed")

    def _apply_filters(
        self,
        page: Page,
        *,
        region: Optional[str],
        date_from: str,
        date_to: str,
        levels: Sequence[str],
    ) -> None:
        self._set_date_field(page, "Date de début", date_from)
        self._set_date_field(page, "Date de fin", date_to)
        if region:
            self._select_combobox_option(page, "Région", region)
        if levels:
            try:
                toggle = page.get_by_role("button", name=re.compile("Niveau", re.I))
                toggle.click()
                for level in levels:
                    option = page.get_by_role("checkbox", name=re.compile(level, re.I))
                    if not option.is_checked():
                        option.check()
                        self._rate_limit()
                toggle.click()
            except PlaywrightError:
                self._logger.warning("Unable to set levels", extra={"levels": levels})

    def _set_date_field(self, page: Page, label: str, value: str) -> None:
        try:
            control = page.get_by_label(label, exact=False)
            control.click()
            control.fill(value)
            control.press("Enter")
            self._rate_limit()
        except PlaywrightError:
            self._logger.warning("Unable to set date", extra={"field": label, "value": value})

    def _select_category(self, page: Page, category: str) -> None:
        try:
            toggle = page.get_by_role("button", name=re.compile("Catégorie", re.I))
            toggle.click()
            labels = {"H": "Hommes", "F": "Dames", "MIXTE": "Mixte"}
            label = labels.get(category.upper(), category)
            option = page.get_by_role("option", name=re.compile(label, re.I))
            option.click()
            self._rate_limit()
        except PlaywrightError:
            self._logger.warning("Unable to select category", extra={"category": category})

    def _select_combobox_option(self, page: Page, label: str, value: str) -> None:
        try:
            toggle = page.get_by_role("button", name=re.compile(label, re.I))
            toggle.click()
            option = page.get_by_role("option", name=re.compile(value, re.I))
            option.click()
            self._rate_limit()
        except PlaywrightError:
            self._logger.warning("Unable to select option", extra={"label": label, "value": value})

    def _refresh_results(self, page: Page) -> None:
        try:
            apply_button = page.get_by_role("button", name=re.compile("Rechercher|Appliquer", re.I))
            if apply_button.is_visible():
                apply_button.click()
                self._rate_limit()
        except PlaywrightError:
            pass

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------
    def _collect_list_items(self, page: Page, limit: int) -> List[ScrapedTournament]:
        items: List[ScrapedTournament] = []
        retries = 0
        while len(items) < limit:
            cards = page.locator("[data-testid='tournament-card']")
            total = cards.count()
            for index in range(total):
                if len(items) >= limit:
                    break
                card = cards.nth(index)
                try:
                    tournament = self._parse_card(page, card)
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.warning("Failed to parse card", extra={"error": str(exc)})
                    continue
                if tournament:
                    items.append(tournament)
            if len(items) >= limit:
                break
            try:
                load_more = page.get_by_role("button", name=re.compile("(Charger|Voir) plus", re.I))
            except PlaywrightError:
                break
            if load_more.is_visible():
                load_more.click()
                self._rate_limit()
                continue
            retries += 1
            if retries >= self.max_retries:
                break
        return items

    def _parse_card(self, page: Page, card: Locator) -> Optional[ScrapedTournament]:
        link = card.get_by_role("link").first
        detail_url = link.get_attribute("href") or ""
        if not detail_url:
            return None
        detail_url = urljoin(page.url, detail_url)
        name = link.inner_text().strip()
        meta_text = card.inner_text().strip()
        category = self._extract_category(meta_text)
        level = self._extract_level(meta_text)

        return self._scrape_detail(page.context, detail_url, name=name, category=category, level=level)

    def _scrape_detail(
        self,
        context: BrowserContext,
        url: str,
        *,
        name: str,
        category: str,
        level: Optional[str],
    ) -> Optional[ScrapedTournament]:
        attempts = 0
        while attempts < self.max_retries:
            attempts += 1
            detail_page = context.new_page()
            try:
                detail_page.goto(url, wait_until="domcontentloaded", timeout=self.request_timeout_ms)
                detail_page.wait_for_load_state("networkidle", timeout=self.request_timeout_ms)
                tournament = self._extract_detail(
                    detail_page, url, name=name, category=category, level=level
                )
                detail_page.close()
                if tournament:
                    return tournament
            except PlaywrightTimeoutError:
                self._logger.warning("Detail page timeout", extra={"url": url, "attempt": attempts})
            except PlaywrightError as exc:
                self._logger.warning("Detail page error", extra={"url": url, "error": str(exc)})
            finally:
                if not detail_page.is_closed():
                    detail_page.close()
            self._rate_limit()
        return None

    def _extract_detail(
        self,
        page: Page,
        url: str,
        *,
        name: str,
        category: str,
        level: Optional[str],
    ) -> ScrapedTournament:
        last_scraped_at = pendulum.now("Europe/Paris").to_iso8601_string()
        clean_name = self._normalise_name(name or page.title())
        header_name = self._safe_text(page.locator("h1")) or clean_name

        info_map = self._extract_info_pairs(page)
        start_date, end_date = self._extract_dates(page, info_map)
        registration_deadline = self._normalise_date(info_map.get("Clôture des inscriptions"))
        club_name = info_map.get("Club organisateur") or info_map.get("Club")
        club_code = info_map.get("Code club")
        organizer = info_map.get("Organisateur")
        city = info_map.get("Ville") or self._extract_city_from_header(page)
        address = info_map.get("Adresse")
        surface = info_map.get("Surface")
        indoor = info_map.get("Type") or info_map.get("Intérieur / Extérieur")
        draw_size = self._safe_int(info_map.get("Tableau"))
        price = self._safe_price(info_map.get("Tarif"))
        status = info_map.get("Statut")
        registration_url = self._extract_registration_url(page, url)
        tournament_id = self._extract_tournament_id(page, url)
        detail_level = level or self._extract_level(info_map.get("Niveau") or "")
        if not detail_level:
            detail_level = self._extract_level(info_map.get("Catégorie") or "")
        detail_category = self._extract_category(info_map.get("Catégorie", "") or category)

        return ScrapedTournament(
            tournament_id=tournament_id,
            name=header_name,
            level=detail_level,
            category=detail_category,
            club_name=self._normalise_text(club_name),
            club_code=self._normalise_text(club_code),
            organizer=self._normalise_text(organizer),
            city=self._normalise_text(city),
            region=self._normalise_text(info_map.get("Région")),
            address=self._normalise_text(address),
            start_date=start_date,
            end_date=end_date,
            registration_deadline=registration_deadline,
            surface=self._normalise_text(surface),
            indoor_outdoor=self._normalise_text(indoor),
            draw_size=draw_size,
            price=price,
            status=self._normalise_text(status),
            detail_url=url,
            registration_url=registration_url,
            last_scraped_at=last_scraped_at,
        )

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------
    def _extract_info_pairs(self, page: Page) -> Dict[str, str]:
        info: Dict[str, str] = {}
        sections = page.locator("[data-testid='tournament-details']")
        if sections.count() == 0:
            sections = page.locator("section")
        for section_index in range(sections.count()):
            section = sections.nth(section_index)
            dts = section.locator("xpath=.//dt")
            dds = section.locator("xpath=.//dd")
            total = min(dts.count(), dds.count())
            for index in range(total):
                try:
                    key = dts.nth(index).inner_text().strip()
                    value = dds.nth(index).inner_text().strip()
                except PlaywrightError:
                    continue
                if key:
                    info[key] = value
        return info

    def _extract_dates(self, page: Page, info_map: Dict[str, str]) -> tuple[str, str]:
        raw_dates = info_map.get("Dates") or self._safe_text(page.locator("[data-testid='tournament-dates']"))
        if raw_dates:
            parts = [part.strip() for part in re.split(r"-|au", raw_dates) if part.strip()]
            if len(parts) == 2:
                start = self._normalise_date(parts[0])
                end = self._normalise_date(parts[1])
                if start and end:
                    return start, end
        fallback = self._normalise_date(info_map.get("Date de début"))
        fallback_end = self._normalise_date(info_map.get("Date de fin"))
        now_date = pendulum.now("Europe/Paris").to_date_string()
        return fallback or now_date, fallback_end or fallback or now_date

    def _extract_registration_url(self, page: Page, default: str) -> str:
        try:
            button = page.get_by_role("link", name=re.compile("(Inscription|S'inscrire)", re.I))
            if button.is_visible():
                href = button.get_attribute("href")
                if href:
                    return urljoin(page.url, href)
        except PlaywrightError:
            pass
        return default

    def _extract_tournament_id(self, page: Page, url: str) -> str:
        try:
            identifier = self._safe_text(page.locator("[data-testid='tournament-id']"))
            if identifier:
                return identifier
        except PlaywrightError:
            pass
        match = re.search(r"(PAD[-_]\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"/(\d{3,})", url)
        if match:
            return match.group(1)
        return str(abs(hash(url)))

    def _extract_category(self, text: str) -> str:
        text = text.upper()
        if "HOM" in text or "HOMME" in text or "MESSIEURS" in text:
            return "H"
        if "DAM" in text or "FEM" in text:
            return "F"
        if "MIX" in text:
            return "MIXTE"
        return "MIXTE"

    def _extract_level(self, text: str) -> Optional[str]:
        match = re.search(r"P\d{2,4}", text.upper())
        return match.group(0) if match else None

    def _extract_city_from_header(self, page: Page) -> Optional[str]:
        subtitle = self._safe_text(page.locator("[data-testid='tournament-location']"))
        if subtitle:
            return subtitle
        return None

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------
    def _normalise_name(self, name: str) -> str:
        return self._normalise_text(name) or "Tournoi de padel"

    def _normalise_text(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None

    def _normalise_date(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            dt = pendulum.parse(str(value), strict=False, tz="Europe/Paris")
            return dt.to_date_string()
        except Exception:
            return None

    def _safe_text(self, locator: Locator) -> Optional[str]:
        try:
            if locator.count() == 0:
                return None
            text = locator.first.inner_text().strip()
            return text or None
        except PlaywrightError:
            return None

    def _safe_int(self, value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        try:
            digits = re.findall(r"\d+", value)
            return int(digits[0]) if digits else None
        except (TypeError, ValueError):
            return None

    def _safe_price(self, value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        cleaned = value.replace("€", "").replace(",", ".")
        digits = re.findall(r"\d+(?:\.\d+)?", cleaned)
        if not digits:
            return None
        try:
            return float(digits[0])
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def _rate_limit(self) -> None:
        if not self.respect_rate_limit:
            return
        delay = random.uniform(*self.random_delay_range)
        time.sleep(delay)

    def _capture_debug_artifacts(self) -> None:
        if not self._page or self._page.is_closed():
            return
        try:
            content = self._page.content()
        except PlaywrightError:
            content = None
        snapshot_dir = Path("data")
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        if content:
            (snapshot_dir / "snapshot.html").write_text(content, encoding="utf-8")
        if self._context:
            try:
                self._context.storage_state(path=str(snapshot_dir / "storage_state.json"))
            except PlaywrightError:
                pass


__all__ = ["ScrapedTournament", "TenUpScraper"]

