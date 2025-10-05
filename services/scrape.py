"""High level helpers and CLI to orchestrate TenUp scraping flows."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from time import perf_counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pendulum
from flask import Flask
from loguru import logger

from extensions import db
from models.tournament import Tournament
from scrapers.tenup import TenUpScraper
from services.tournament_store import TournamentStore

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "app.db"
DEFAULT_JSON_PATH = DATA_DIR / "tournaments.json"
CONFIG_PATH = BASE_DIR / "config.json"

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


def _load_config(path: Path = CONFIG_PATH) -> Dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Missing configuration file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _ensure_storage(json_path: Path) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.touch(exist_ok=True)


def _create_app(sqlite_path: Path) -> Flask:
    app = Flask("tenpadel-scraper")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{sqlite_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    return app


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape TenUp tournaments and persist them to the local storage",
    )
    parser.add_argument(
        "--category",
        action="append",
        help="Filtrer par catégorie (H, F, MIXTE). Peut être utilisé plusieurs fois.",
    )
    parser.add_argument("--from", dest="date_from", help="Date de début (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="Date de fin (YYYY-MM-DD)")
    parser.add_argument("--region", help="Filtrer par région")
    parser.add_argument("--city", help="Filtrer par ville")
    parser.add_argument("--radius-km", type=int, help="Rayon géographique en kilomètres")
    parser.add_argument(
        "--level",
        action="append",
        help="Filtrer par niveau (ex: P250, P500). Peut être utilisé plusieurs fois.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Nombre maximum de tournois à récupérer (par catégorie).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Fichier JSON de sortie (défaut: data/tournaments.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ne pas persister en base, afficher seulement le résumé.",
    )
    return parser


def _resolve_cli_parameters(config: Dict[str, object], args: argparse.Namespace) -> Dict[str, object]:
    tenup_config = config.get("tenup", {}) if config else {}

    categories = [token.strip().upper() for token in (args.category or []) if token.strip()]
    if not categories:
        default_categories = tenup_config.get("default_categories") or DEFAULT_CATEGORIES
        categories = [str(token).upper() for token in default_categories]

    levels = [token.strip().upper() for token in (args.level or []) if token.strip()]

    limit = args.limit
    if limit in (None, 0):
        limit = tenup_config.get("max_results")

    radius = args.radius_km
    if radius in (None, 0):
        radius = tenup_config.get("default_radius_km")

    region = args.region or tenup_config.get("default_region")
    city = args.city or tenup_config.get("default_city")

    return {
        "categories": categories,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "region": region,
        "city": city,
        "radius_km": radius,
        "level": levels or None,
        "limit": limit,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        config = _load_config()
    except FileNotFoundError as exc:  # pragma: no cover - CLI usage
        parser.error(str(exc))
        return 2

    json_output = args.output or DEFAULT_JSON_PATH
    _ensure_storage(json_output)

    flask_app = _create_app(DATABASE_PATH)
    params = _resolve_cli_parameters(config, args)
    store = TournamentStore(db, json_output)

    with flask_app.app_context():
        db.create_all()
        try:
            tournaments, meta = scrape_tenup(config, **params)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Scraping failed", error=str(exc))
            print(f"❌ Scraping TenUp échoué: {exc}", file=sys.stderr)
            return 1

        total = len(tournaments)
        print(
            "🎯 TenUp scraping terminé",
            f"(catégories={meta.get('categories')}, période={meta.get('date_from')}->{meta.get('date_to')})",
        )
        print(f"   → Tournois récupérés: {total}")

        if args.dry_run:
            print("ℹ️ Mode --dry-run: aucune écriture en base/JSON.")
            return 0

        stats = store.upsert_many(tournaments)
        summary = stats.as_dict()
        print(
            "✅ Persistance SQLite/JSON terminée:",
            f"insérés={summary['inserted']}",
            f"mis-à-jour={summary['updated']}",
            f"inchangés={summary['skipped']}",
        )
        print(f"   → Base SQLite: {DATABASE_PATH}")
        print(f"   → Export JSON : {json_output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI usage
    raise SystemExit(main())
