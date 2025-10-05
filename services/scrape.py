"""High level helpers to orchestrate TenUp scraping flows."""
from __future__ import annotations

from time import perf_counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pendulum

from loguru import logger

from models.tournament import Tournament
from scrapers.tenup import TenUpScraper


DEFAULT_CATEGORIES = ("H", "F", "MIXTE")


def compute_date_range(
    date_from: Optional[str], date_to: Optional[str], default_window_days: int = 60
) -> Tuple[str, str]:
    tz = "Europe/Paris"
    start = pendulum.parse(date_from, strict=False) if date_from else pendulum.now(tz)
    end = pendulum.parse(date_to, strict=False) if date_to else start.add(days=default_window_days)
    if end < start:
        start, end = end, start
    return start.to_date_string(), end.to_date_string()


def scrape_tenup(
    config: Dict[str, object],
    categories: Optional[Iterable[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    radius_km: Optional[int] = None,
    level: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> Tuple[List[Tournament], Dict[str, object]]:
    """Scrape TenUp tournaments and return the normalised objects along meta information."""

    tenup_config = config.get("tenup", {}) if config else {}
    categories = list(categories or DEFAULT_CATEGORIES)
    start_date, end_date = compute_date_range(date_from, date_to)

    geo: Dict[str, object] = {}
    if region:
        geo["region"] = region
    if city:
        geo["city"] = city
    if radius_km is not None:
        geo["radius_km"] = radius_km

    levels = list(level or [])

    scraper = TenUpScraper(tenup_config)
    started = perf_counter()
    tournaments = scraper.fetch_all(
        categories=categories,
        date_from=start_date,
        date_to=end_date,
        geo=geo,
        level=levels,
        limit=limit,
    )
    duration = perf_counter() - started
    logger.bind(component="scrape").info(
        "Scrape finished", categories=categories, fetched=len(tournaments), duration=duration
    )
    return tournaments, {
        "duration_s": round(duration, 3),
        "categories": categories,
        "date_from": start_date,
        "date_to": end_date,
        "level": levels,
        "geo": geo,
        "fetched": len(tournaments),
    }
