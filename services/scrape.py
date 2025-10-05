"""High-level orchestration to scrape TenUp tournaments with Playwright."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from flask import Flask
from playwright.sync_api import sync_playwright

from extensions import db
from scrapers.tenup import (
    TENUP_URL,
    accept_cookies,
    extract_cards,
    search_and_sort,
    select_discipline_padel,
    select_ligue_paca_alpes_maritimes,
    warn_client_side_date_filter,
)
from services.tournament_store import TournamentStore

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_PATH = DATA_DIR / "logs" / "tenup.log"
DATABASE_PATH = DATA_DIR / "app.db"
JSON_PATH = DATA_DIR / "tournaments.json"

DEFAULT_REGION = "PROVENCE ALPES COTE D’AZUR"
DEFAULT_COMMITTEE = "ALPES MARITIMES"


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.touch(exist_ok=True)


def _configure_logging() -> logging.Logger:
    logger = logging.getLogger()
    if logger.handlers:
        return logging.getLogger("services.scrape")

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logging.getLogger("services.scrape")


def _create_app(sqlite_path: Path) -> Flask:
    app = Flask("tenup-scraper")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{sqlite_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    return app


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _filter_and_normalise(
    items: Iterable[dict],
    *,
    region: str,
    date_from: Optional[str],
    date_to: Optional[str],
    limit: int,
    logger: logging.Logger,
) -> List[dict]:
    start_bound = _parse_date(date_from)
    end_bound = _parse_date(date_to)

    unique: dict[str, dict] = {}
    for raw in items:
        tid = raw.get("tournament_id")
        start_value = raw.get("start_date")
        end_value = raw.get("end_date") or start_value
        if not tid or not start_value:
            continue

        start_date = _parse_date(start_value)
        end_date = _parse_date(end_value) if end_value else None
        if start_bound and (not start_date or start_date < start_bound):
            continue
        if end_bound:
            if not end_date:
                continue
            if end_date > end_bound:
                continue

        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat() if end_date else start_iso

        normalised = {
            "tournament_id": tid,
            "name": raw.get("name", ""),
            "level": raw.get("level"),
            "category": raw.get("category") or "PADEL",
            "club_name": raw.get("club_name"),
            "club_code": None,
            "organizer": None,
            "city": raw.get("city"),
            "region": region,
            "address": None,
            "start_date": start_iso,
            "end_date": end_iso,
            "registration_deadline": None,
            "surface": None,
            "indoor_outdoor": None,
            "draw_size": None,
            "price": None,
            "status": None,
            "detail_url": raw.get("detail_url") or TENUP_URL,
            "registration_url": raw.get("registration_url"),
        }
        unique[tid] = normalised

    filtered = list(unique.values())
    filtered.sort(key=lambda item: (item["start_date"], item["tournament_id"]))
    if limit:
        filtered = filtered[:limit]

    logger.info("Fetched %d tournaments.", len(filtered))
    return filtered


def _stamp_records(records: Iterable[dict]) -> List[dict]:
    now_iso = datetime.now(timezone.utc).isoformat()
    stamped: List[dict] = []
    for record in records:
        payload = dict(record)
        payload.setdefault("last_scraped_at", now_iso)
        payload.setdefault("registration_url", None)
        stamped.append(payload)
    return stamped


def _persist(records: Sequence[dict]) -> None:
    app = _create_app(DATABASE_PATH)
    with app.app_context():
        db.create_all()
        store = TournamentStore(db, JSON_PATH)
        store.upsert_many(records)


def scrape_all(
    region: str,
    committee: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 500,
) -> List[dict]:
    """Scrape TenUp tournaments, filter client-side and persist results."""

    _ensure_storage()
    logger = _configure_logging()

    logger.info(
        "Starting TenUp scrape",
        extra={"region": region, "committee": committee, "limit": limit},
    )
    warn_client_side_date_filter(logger)

    raw_items: List[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto(TENUP_URL, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            accept_cookies(page)
            select_ligue_paca_alpes_maritimes(
                page, region=region, committee=committee, logger=logger
            )
            select_discipline_padel(page, logger=logger)
            search_and_sort(page, logger=logger)
            raw_items = extract_cards(page, limit=limit)
        finally:
            context.close()
            browser.close()

    processed = _filter_and_normalise(
        raw_items,
        region=region,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        logger=logger,
    )
    stamped = _stamp_records(processed)

    JSON_PATH.write_text(
        json.dumps(stamped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _persist(stamped)
    return stamped


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape TenUp tournaments (UI only)")
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help="Nom de la ligue (par défaut: PROVENCE ALPES COTE D’AZUR)",
    )
    parser.add_argument(
        "--committee",
        default=DEFAULT_COMMITTEE,
        help="Nom du comité (par défaut: ALPES MARITIMES)",
    )
    parser.add_argument("--date-from", dest="date_from", help="Date de début YYYY-MM-DD")
    parser.add_argument("--date-to", dest="date_to", help="Date de fin YYYY-MM-DD")
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Nombre maximum de tournois à retourner",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    results = scrape_all(
        region=args.region,
        committee=args.committee,
        date_from=args.date_from,
        date_to=args.date_to,
        limit=int(args.limit or 500),
    )

    print(f"🎯 TenUp scraping terminé – {len(results)} tournois")
    print(f"   → Export JSON : {JSON_PATH}")
    print(f"   → Base SQLite: {DATABASE_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
