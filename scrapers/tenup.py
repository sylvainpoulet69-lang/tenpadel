"""Scraper implementation for the TenUp padel tournaments catalogue."""
from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import httpx
import pendulum
from loguru import logger
from playwright.sync_api import (Error as PlaywrightError, Locator, Page,
                                 TimeoutError as PlaywrightTimeoutError,
                                 sync_playwright)

from models.tournament import Tournament

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class FetchContext:
    category: str
    date_from: str
    date_to: str
    geo: Dict[str, object]
    level: Sequence[str]
    limit: int


class TenUpScraper:
    """Fetch padel tournaments from TenUp using Playwright or the public API."""

    def __init__(self, config: Dict[str, object]) -> None:
        self.config = config or {}
        self.base_url = self.config.get("base_url", "https://tenup.fft.fr/recherche/tournois")
        self.headless = bool(self.config.get("headless", True))
        self.request_timeout = int(self.config.get("request_timeout_ms", 30000))
        self.max_results = int(self.config.get("max_results", 500))
        self.respect_rate_limit = bool(self.config.get("respect_rate_limit", True))
        self.log = logger.bind(component="TenUpScraper")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_tournaments(
        self,
        category: str,
        date_from: str,
        date_to: str,
        geo: Dict[str, object],
        level: Sequence[str],
        limit: int = 500,
    ) -> List[Tournament]:
        """Fetch tournaments for a single category."""

        ctx = FetchContext(
            category=category,
            date_from=date_from,
            date_to=date_to,
            geo=geo,
            level=level,
            limit=min(limit, self.max_results),
        )

        self.log.info(
            "Fetching tournaments", category=ctx.category, period=f"{ctx.date_from}->{ctx.date_to}", level=list(level)
        )

        items: List[Tournament] = []
        try:
            api_payload = self._fetch_via_api(ctx)
            if api_payload:
                items.extend(api_payload)
        except Exception as exc:  # pragma: no cover - defensive logging
            self.log.warning("API lookup failed, falling back to Playwright", error=str(exc))

        if not items:
            try:
                items.extend(self._fetch_via_playwright(ctx))
            except Exception as exc:  # pragma: no cover - defensive logging
                self.log.error("Playwright scraping failed", error=str(exc))

        deduped = self._deduplicate(items)
        self.log.info("Fetched %d tournaments", len(deduped))
        return deduped[: ctx.limit]

    def fetch_all(
        self,
        categories: Iterable[str],
        date_from: str,
        date_to: str,
        geo: Optional[Dict[str, object]] = None,
        level: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> List[Tournament]:
        """Fetch tournaments for several categories."""

        geo = geo or {}
        level = level or []
        limit = limit or self.max_results
        aggregated: List[Tournament] = []
        for category in categories:
            tournaments = self.fetch_tournaments(category, date_from, date_to, geo, level, limit)
            aggregated.extend(tournaments)
            if self.respect_rate_limit:
                time.sleep(random.uniform(0.3, 0.9))
        return self._deduplicate(aggregated)

    # ------------------------------------------------------------------
    # API fetching helpers
    # ------------------------------------------------------------------
    def _fetch_via_api(self, ctx: FetchContext) -> List[Tournament]:
        """Attempt to use TenUp's JSON API if the endpoint is known."""

        endpoint = self.config.get("api_endpoint")
        if not endpoint:
            return []

        params = self._build_query_params(ctx)
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        timeout = self.request_timeout / 1000.0
        response = httpx.get(endpoint, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return self._normalise_api_payload(data)

    def _build_query_params(self, ctx: FetchContext) -> Dict[str, object]:
        params: Dict[str, object] = {
            "discipline": "PADEL",
            "category": ctx.category,
            "dateFrom": ctx.date_from,
            "dateTo": ctx.date_to,
            "limit": ctx.limit,
        }
        if ctx.geo.get("region"):
            params["region"] = ctx.geo["region"]
        if ctx.geo.get("city"):
            params["city"] = ctx.geo["city"]
        if ctx.geo.get("radius_km"):
            params["radius"] = ctx.geo["radius_km"]
        if ctx.level:
            params["level"] = ",".join(ctx.level)
        return params

    def _normalise_api_payload(self, payload: Dict[str, object]) -> List[Tournament]:
        tournaments: List[Tournament] = []
        results = payload.get("items") or payload.get("data") or []
        if not isinstance(results, list):
            return []

        for raw in results:
            tournament = self._build_tournament(raw)
            if tournament:
                tournaments.append(tournament)
        return tournaments

    # ------------------------------------------------------------------
    # Playwright fallback
    # ------------------------------------------------------------------
    def _fetch_via_playwright(self, ctx: FetchContext) -> List[Tournament]:
        """Drive the TenUp UI with Playwright when no API is available."""

        items: List[Tournament] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            context = browser.new_context(
                locale="fr-FR",
                timezone_id="Europe/Paris",
                user_agent=_USER_AGENT,
            )
            page = context.new_page()
            try:
                self._load_page(page)
                self._accept_cookies(page)
                self._apply_filters(page, ctx)
                items = self._collect_from_dom(page, ctx.limit)
            finally:
                context.close()
                browser.close()
        return items

    def _load_page(self, page: Page) -> None:
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=self.request_timeout)
        page.wait_for_load_state("networkidle", timeout=self.request_timeout)

    def _accept_cookies(self, page: Page) -> None:
        try:
            button = page.get_by_role("button", name="Tout accepter", exact=True)
            if button.is_visible():
                button.click()
                page.wait_for_load_state("networkidle", timeout=self.request_timeout)
        except PlaywrightTimeoutError:
            return
        except PlaywrightError:  # pragma: no cover - defensive
            return

    def _apply_filters(self, page: Page, ctx: FetchContext) -> None:
        self._select_discipline(page)
        self._select_category(page, ctx.category)
        self._set_date_range(page, ctx.date_from, ctx.date_to)
        if ctx.geo.get("region"):
            self._select_region(page, str(ctx.geo["region"]))
        if ctx.geo.get("city"):
            self._select_city(page, str(ctx.geo["city"]), ctx.geo.get("radius_km"))
        if ctx.level:
            self._select_levels(page, ctx.level)

    def _select_discipline(self, page: Page) -> None:
        try:
            page.get_by_role("button", name="Discipline").click()
            page.get_by_role("option", name="Padel").click()
        except PlaywrightError:
            self.log.warning("Unable to select discipline – the page structure may have changed")

    def _select_category(self, page: Page, category: str) -> None:
        labels = {"H": "Hommes", "F": "Dames", "MIXTE": "Mixte"}
        try:
            page.get_by_role("button", name="Catégorie").click()
            page.get_by_role("option", name=labels.get(category, category)).click()
        except PlaywrightError:
            self.log.warning("Unable to select category %s", category)

    def _set_date_range(self, page: Page, date_from: str, date_to: str) -> None:
        try:
            page.get_by_label("Date de début").fill(date_from)
            page.get_by_label("Date de fin").fill(date_to)
            page.get_by_label("Date de fin").press("Enter")
        except PlaywrightError:
            self.log.warning("Unable to set date range")

    def _select_region(self, page: Page, region: str) -> None:
        try:
            page.get_by_role("button", name="Région").click()
            page.get_by_role("option", name=region).click()
        except PlaywrightError:
            self.log.warning("Unable to select region %s", region)

    def _select_city(self, page: Page, city: str, radius: Optional[object]) -> None:
        try:
            page.get_by_label("Ville").fill(city)
            page.get_by_label("Ville").press("Enter")
            if radius:
                page.get_by_label("Rayon").fill(str(radius))
        except PlaywrightError:
            self.log.warning("Unable to select city %s", city)

    def _select_levels(self, page: Page, levels: Sequence[str]) -> None:
        try:
            page.get_by_role("button", name="Niveau").click()
            for level in levels:
                option = page.get_by_role("checkbox", name=level)
                if option.is_checked():
                    continue
                option.check()
            page.get_by_role("button", name="Niveau").click()
        except PlaywrightError:
            self.log.warning("Unable to select levels %s", levels)

    def _collect_from_dom(self, page: Page, limit: int) -> List[Tournament]:
        tournaments: List[Tournament] = []
        seen_urls: set[str] = set()
        while True:
            cards = page.locator("[data-testid='tournament-card']")
            count = cards.count()
            for index in range(count):
                card = cards.nth(index)
                url = card.get_by_role("link").first.get_attribute("href") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                tournament = self._build_tournament_from_card(card)
                if tournament:
                    tournaments.append(tournament)
                if len(tournaments) >= limit:
                    return tournaments
            load_more = page.get_by_role("button", name="Charger plus")
            if load_more.is_visible():
                load_more.click()
                page.wait_for_load_state("networkidle", timeout=self.request_timeout)
                time.sleep(random.uniform(0.3, 0.9))
                continue
            break
        return tournaments

    def _build_tournament_from_card(self, card: Locator) -> Optional[Tournament]:
        try:
            link = card.get_by_role("link").first
            href = link.get_attribute("href") or ""
            title = link.inner_text().strip()
            meta = card.inner_text()
            dates = card.locator("[data-role='dates']").first.inner_text()
        except PlaywrightError:
            return None

        raw = {
            "url": href,
            "title": title,
            "meta": meta,
            "dates": dates,
        }
        return self._build_tournament(raw)

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------
    def _build_tournament(self, raw: Dict[str, object]) -> Optional[Tournament]:
        try:
            external_id = self._extract_external_id(raw)
            start_date, end_date = self._extract_dates(raw)
            title = str(raw.get("title") or raw.get("name") or "Tournoi TenUp").strip()
            city = self._normalise_value(raw, ["city", "ville"])
            postal_code = self._normalise_value(raw, ["postalCode", "code_postal", "postal_code"])
            region = self._normalise_value(raw, ["region"])
            club_name = self._normalise_value(raw, ["club", "clubName", "club_name"])
            level = self._normalise_value(raw, ["level", "categorie"])
            price = self._normalise_price(raw)
            inscriptions_open = self._normalise_bool(raw.get("inscriptions_open") or raw.get("open"))
            slots_total = self._normalise_int(raw.get("slots_total") or raw.get("slotsTotal"))
            slots_taken = self._normalise_int(raw.get("slots_taken") or raw.get("slotsTaken"))
            registration_url = self._extract_url(raw, "registration_url")
            details_url = self._extract_url(raw, "details_url") or registration_url

            tournament = Tournament(
                external_id=external_id,
                title=title,
                discipline="PADEL",
                category=self._normalise_category(raw),
                level=level,
                start_date=start_date,
                end_date=end_date,
                city=city,
                postal_code=postal_code,
                region=region,
                club_name=club_name,
                price=price,
                registration_url=registration_url,
                details_url=details_url,
                inscriptions_open=inscriptions_open,
                slots_total=slots_total,
                slots_taken=slots_taken,
                created_at=pendulum.now("Europe/Paris").to_iso8601_string(),
            )
            return tournament
        except Exception as exc:  # pragma: no cover - defensive
            self.log.warning("Failed to normalise tournament", error=str(exc), raw=raw)
            return None

    def _extract_external_id(self, raw: Dict[str, object]) -> str:
        for key in ("external_id", "id", "uid"):
            if raw.get(key):
                return str(raw[key])
        url = self._extract_url(raw, "details_url") or self._extract_url(raw, "registration_url")
        return str(abs(hash(url)))

    def _extract_dates(self, raw: Dict[str, object]) -> tuple[str, str]:
        for key in ("start_date", "dateStart", "startDate"):
            if raw.get(key):
                start = pendulum.parse(str(raw[key]), strict=False)
                break
        else:
            start = pendulum.now("Europe/Paris")
        for key in ("end_date", "dateEnd", "endDate"):
            if raw.get(key):
                end = pendulum.parse(str(raw[key]), strict=False)
                break
        else:
            end = start
        return start.to_date_string(), end.to_date_string()

    def _normalise_value(self, raw: Dict[str, object], keys: Sequence[str]) -> Optional[str]:
        for key in keys:
            if raw.get(key):
                value = str(raw[key]).strip()
                if value:
                    return value
        return None

    def _normalise_category(self, raw: Dict[str, object]) -> str:
        category = (self._normalise_value(raw, ["category", "sex", "genre"]) or "MIXTE").upper()
        if category.startswith("H") or category in {"H", "HOMME", "HOMMES"}:
            return "H"
        if category.startswith("F") or category in {"F", "FEMME", "DAM", "DAMES"}:
            return "F"
        return "MIXTE"

    def _normalise_price(self, raw: Dict[str, object]) -> Optional[float]:
        value = raw.get("price") or raw.get("tarif")
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", "."))
        except ValueError:
            return None

    def _normalise_bool(self, value: object) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "oui", "open"}:
            return True
        if text in {"false", "0", "non", "closed"}:
            return False
        return None

    def _normalise_int(self, value: object) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extract_url(self, raw: Dict[str, object], key: str) -> str:
        value = raw.get(key)
        if value:
            return str(value)
        url = raw.get("url") or raw.get("link") or raw.get("href")
        if url:
            return str(url)
        return self.base_url

    def _deduplicate(self, items: Iterable[Tournament]) -> List[Tournament]:
        deduped: Dict[tuple[str, str], Tournament] = {}
        for item in items:
            key = (item.external_id, item.start_date)
            if key not in deduped:
                deduped[key] = item
        return list(deduped.values())


def _load_config() -> Dict[str, object]:
    if not CONFIG_PATH.exists():  # pragma: no cover - CLI usage
        raise FileNotFoundError(f"Missing configuration file: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _cli_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape TenUp padel tournaments")
    parser.add_argument("--category", action="append", help="Filtrer par catégorie (H, F, MIXTE)")
    parser.add_argument("--from", dest="date_from", help="Date de début (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="Date de fin (YYYY-MM-DD)")
    parser.add_argument("--region", help="Filtrer par région")
    parser.add_argument("--city", help="Filtrer par ville")
    parser.add_argument("--radius-km", type=int, help="Rayon géographique en kilomètres")
    parser.add_argument("--level", action="append", help="Filtrer par niveau (P25, P100, ...)")
    parser.add_argument("--limit", type=int, default=200, help="Nombre maximum de tournois à récupérer")
    parser.add_argument("--output", help="Fichier JSON de sortie")
    parser.add_argument("--dry-run", action="store_true", help="Écrire un JSON de démonstration")
    return parser.parse_args(argv)


def _cli_main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - CLI entry point
    args = _cli_args(argv)
    config = _load_config()
    scraper = TenUpScraper(config.get("tenup", {}))

    categories = [token.upper() for token in (args.category or []) if token]
    geo: Dict[str, object] = {}
    if args.region:
        geo["region"] = args.region
    if args.city:
        geo["city"] = args.city
    if args.radius_km is not None:
        geo["radius_km"] = args.radius_km
    levels = [token.upper() for token in (args.level or []) if token]

    today = pendulum.now("Europe/Paris")
    start_date = args.date_from or today.to_date_string()
    end_date = args.date_to or today.add(days=60).to_date_string()

    tournaments = scraper.fetch_all(
        categories=categories or ("H", "F", "MIXTE"),
        date_from=start_date,
        date_to=end_date,
        geo=geo,
        level=levels,
        limit=args.limit,
    )
    if args.dry_run:
        output_path = Path(args.output or "data/tenup-sample.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [tournament.model_dump() for tournament in tournaments]
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Écriture de {len(tournaments)} tournois dans {output_path}")
    else:
        for tournament in tournaments:
            print(json.dumps(tournament.model_dump(), ensure_ascii=False))
    print(f"Total récupéré: {len(tournaments)}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - CLI entry point
    return _cli_main(argv)


if __name__ == "__main__":  # pragma: no cover - CLI behaviour
    raise SystemExit(main())

