"""High level orchestration for scraping TenUp tournaments."""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Iterable, List, Optional, Sequence

import pendulum
from flask import Flask

from extensions import db
from scrapers.tenup import ScrapedTournament, TenUpScraper
from services.tournament_store import TournamentStore

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "app.db"
JSON_PATH = DATA_DIR / "tournaments.json"
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = DATA_DIR / "logs" / "tenup.log"


DEFAULT_LEVELS = ["P100", "P250", "P500", "P1000", "P1500", "P2000"]
DEFAULT_CATEGORIES = ["H", "F", "MIXTE"]


@dataclass(slots=True)
class ScrapeParameters:
    region: str
    date_from: str
    date_to: str
    categories: List[str]
    levels: List[str]
    limit: int


def _load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.touch(exist_ok=True)


def _create_app(sqlite_path: Path) -> Flask:
    app = Flask("tenpadel-scraper")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{sqlite_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TENUP_CONFIG=_load_config().get("tenup", {}),
    )
    db.init_app(app)
    return app


def _compute_date_range(
    date_from: Optional[str], date_to: Optional[str], default_window_days: int = 60
) -> tuple[str, str]:
    tz = "Europe/Paris"
    start = pendulum.parse(date_from, strict=False) if date_from else pendulum.now(tz)
    end = pendulum.parse(date_to, strict=False) if date_to else start.add(days=default_window_days)
    if end < start:
        start, end = end, start
    return start.to_date_string(), end.to_date_string()


def _parse_cli_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape TenUp tournaments (Playwright only)")
    parser.add_argument("--region", help="Région administrative à filtrer")
    parser.add_argument("--from", dest="date_from", help="Date de début (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="Date de fin (YYYY-MM-DD)")
    parser.add_argument(
        "--category",
        action="append",
        help="Catégorie à inclure (H, F, MIXTE). Peut être utilisée plusieurs fois.",
    )
    parser.add_argument(
        "--level",
        action="append",
        help="Niveau à inclure (P100, P250, ...). Peut être utilisée plusieurs fois.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Nombre maximum de tournois à collecter.",
    )
    return parser.parse_args(argv)


def _resolve_parameters(config: dict, args: argparse.Namespace) -> ScrapeParameters:
    tenup_cfg = config.get("tenup", {})
    region = args.region or tenup_cfg.get("default_region", "")

    tz = "Europe/Paris"
    now = pendulum.now(tz)
    start = pendulum.parse(args.date_from, strict=False) if args.date_from else now
    end = pendulum.parse(args.date_to, strict=False) if args.date_to else now.add(days=60)
    if end < start:
        start, end = end, start

    categories = [token.strip().upper() for token in (args.category or []) if token]
    if not categories:
        categories = [
            str(token).upper()
            for token in tenup_cfg.get("default_categories", DEFAULT_CATEGORIES)
        ]

    levels = [token.strip().upper() for token in (args.level or []) if token]
    if not levels:
        levels = [
            str(token).upper() for token in tenup_cfg.get("default_levels", DEFAULT_LEVELS)
        ]

    limit = max(1, min(int(args.limit or tenup_cfg.get("max_results", 200)), 1000))

    return ScrapeParameters(
        region=region,
        date_from=start.to_date_string(),
        date_to=end.to_date_string(),
        categories=categories,
        levels=levels,
        limit=limit,
    )


def _configure_logging() -> None:
    root_logger = logging.getLogger()
    if any(
        isinstance(handler, logging.FileHandler)
        and getattr(handler, "baseFilename", "") == str(LOG_PATH)
        for handler in root_logger.handlers
    ):
        return

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)


def scrape_tenup(
    config: dict,
    *,
    categories: Optional[Iterable[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    radius_km: Optional[int] = None,
    level: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
) -> tuple[List[dict], dict]:
    """Scrape TenUp tournaments without persisting the results."""

    _ensure_storage()
    _configure_logging()

    tenup_cfg = (config or {}).get("tenup", {})

    resolved_categories = [token.strip().upper() for token in (categories or []) if token]
    if not resolved_categories:
        resolved_categories = [
            str(token).upper()
            for token in tenup_cfg.get("default_categories", DEFAULT_CATEGORIES)
        ]

    resolved_levels = [token.strip().upper() for token in (level or []) if token]
    if not resolved_levels:
        resolved_levels = [
            str(token).upper() for token in tenup_cfg.get("default_levels", DEFAULT_LEVELS)
        ]

    start_date, end_date = _compute_date_range(date_from, date_to)

    limit_value = int(limit or tenup_cfg.get("max_results", 200))
    limit_value = max(1, min(limit_value, 1000))

    region_value = region or tenup_cfg.get("default_region")

    scraper = TenUpScraper(
        base_url=tenup_cfg.get("base_url", "https://tenup.fft.fr/recherche/tournois"),
        headless=bool(tenup_cfg.get("headless", True)),
        request_timeout_ms=int(tenup_cfg.get("request_timeout_ms", 30000)),
        respect_rate_limit=bool(tenup_cfg.get("respect_rate_limit", True)),
        log_path=LOG_PATH,
        random_delay_range=(1.2, 2.0),
        max_retries=3,
    )

    started = perf_counter()
    tournaments: List[ScrapedTournament] = scraper.scrape(
        region=region_value,
        date_from=start_date,
        date_to=end_date,
        categories=resolved_categories,
        levels=resolved_levels,
        limit=limit_value,
    )
    duration = perf_counter() - started

    payload = [item.asdict() for item in tournaments]
    meta = {
        "duration_s": round(duration, 3),
        "categories": resolved_categories,
        "date_from": start_date,
        "date_to": end_date,
        "level": resolved_levels,
        "geo": {"region": region_value, "city": city, "radius_km": radius_km},
        "fetched": len(payload),
    }
    return payload, meta


def scrape_all(
    region: str,
    date_from: str,
    date_to: str,
    categories: Iterable[str],
    levels: Iterable[str],
    limit: int = 200,
) -> List[dict]:
    """Scrape TenUp tournaments and persist results to JSON and SQLite."""

    _ensure_storage()
    _configure_logging()

    config = _load_config()
    payload, _meta = scrape_tenup(
        config,
        categories=list(categories),
        date_from=date_from,
        date_to=date_to,
        region=region,
        level=list(levels),
        limit=limit,
    )

    app = _create_app(DATABASE_PATH)
    with app.app_context():
        db.create_all()
        store = TournamentStore(db, JSON_PATH)
        store.upsert_many(payload)

    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_cli_arguments(argv)
    config = _load_config()
    params = _resolve_parameters(config, args)

    _ensure_storage()
    _configure_logging()

    logging.getLogger("services.scrape").info(
        "Scraping TenUp",
        extra={
            "region": params.region,
            "date_from": params.date_from,
            "date_to": params.date_to,
            "categories": params.categories,
            "levels": params.levels,
            "limit": params.limit,
        },
    )

    results = scrape_all(
        region=params.region,
        date_from=params.date_from,
        date_to=params.date_to,
        categories=params.categories,
        levels=params.levels,
        limit=params.limit,
    )

    print(f"🎯 TenUp scraping terminé – {len(results)} tournois")
    print(f"   → Export JSON : {JSON_PATH}")
    print(f"   → Base SQLite: {DATABASE_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI usage
    raise SystemExit(main())

