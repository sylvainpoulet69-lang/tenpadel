"""Padel tournament calendar and registration application."""
from __future__ import annotations

import csv
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional

from flask import (Flask, Response, abort, jsonify, render_template, request,
                   send_file)

CONFIG_PATH = Path("config.json")
TOURNAMENTS_PATH = Path("data/tournaments.json")
REGISTRATIONS_PATH = Path("data/registrations.csv")
CSV_HEADERS = [
    "timestamp",
    "tournament_id",
    "tournament_date",
    "tournament_title",
    "tournament_url",
    "club",
    "sex",
    "category",
    "player1_name",
    "player1_licence",
    "player1_phone",
    "player1_email",
    "player2_name",
    "player2_licence",
    "player2_phone",
    "player2_email",
    "notes",
    "source_ip",
]

logger = logging.getLogger("tenpadel.app")


@dataclass
class RegistrationConfig:
    max_teams_per_tournament: Optional[int]
    licence_regex: str
    throttle_window_seconds: int
    throttle_max_submissions: int


@dataclass
class ClubToken:
    token: str
    club_slug: str
    label: str


app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def load_config() -> Dict[str, object]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json is missing")
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_registration_file() -> None:
    REGISTRATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRATIONS_PATH.exists() or REGISTRATIONS_PATH.stat().st_size == 0:
        with REGISTRATIONS_PATH.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(CSV_HEADERS)


def load_registrations() -> List[Dict[str, str]]:
    ensure_registration_file()
    with REGISTRATIONS_PATH.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def write_registration_row(row: Dict[str, str]) -> None:
    ensure_registration_file()
    with REGISTRATIONS_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS)
        writer.writerow(row)


def normalise_text(value: Optional[str]) -> str:
    return (value or "").strip()


def normalise_licence(value: str) -> str:
    return normalise_text(value).upper()


def normalise_club(value: str) -> str:
    return normalise_text(value).upper()


CONFIG = load_config()
REGISTRATION_CONF = RegistrationConfig(
    max_teams_per_tournament=(
        int(CONFIG.get("registration", {}).get("max_teams_per_tournament"))
        if CONFIG.get("registration", {}).get("max_teams_per_tournament")
        not in (None, "", 0)
        else None
    ),
    licence_regex=CONFIG.get("registration", {}).get("licence_regex", r"^[A-Z0-9]{6,12}$"),
    throttle_window_seconds=int(CONFIG.get("registration", {}).get("throttle_window_seconds", 60)),
    throttle_max_submissions=int(CONFIG.get("registration", {}).get("throttle_max_submissions", 2)),
)
LICENCE_PATTERN = re.compile(REGISTRATION_CONF.licence_regex, re.IGNORECASE)

CLUB_TOKENS: Dict[str, ClubToken] = {}
for token, payload in CONFIG.get("club_tokens", {}).items():
    CLUB_TOKENS[token] = ClubToken(
        token=token,
        club_slug=normalise_club(payload.get("club_slug", "")),
        label=payload.get("label", token),
    )

submission_tracker: Dict[str, List[float]] = {}


def prune_submission_tracker(now: float) -> None:
    window = REGISTRATION_CONF.throttle_window_seconds
    for ip, timestamps in list(submission_tracker.items()):
        submission_tracker[ip] = [ts for ts in timestamps if now - ts <= window]
        if not submission_tracker[ip]:
            submission_tracker.pop(ip, None)


@app.route("/")
def index() -> str:
    return render_template(
        "index.html",
        licence_regex=REGISTRATION_CONF.licence_regex,
        max_teams=REGISTRATION_CONF.max_teams_per_tournament,
    )


@app.route("/api/tournaments")
def api_tournaments() -> Response:
    if not TOURNAMENTS_PATH.exists():
        return jsonify({"generated_at": None, "source": DEFAULT_SOURCE, "tournaments": []})
    with TOURNAMENTS_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return jsonify(data)


DEFAULT_SOURCE = "tenup_scrape_playwright_paged"


def _validate_payload(payload: Dict[str, object]) -> Optional[Response]:
    required_fields = [
        "tournament_id",
        "tournament_title",
        "tournament_date",
        "tournament_url",
        "club",
        "sex",
        "category",
        "player1_licence",
        "player2_licence",
        "player1_phone",
    ]
    missing = [field for field in required_fields if not normalise_text(payload.get(field))]
    if missing:
        return jsonify({"ok": False, "message": f"Champs manquants: {', '.join(missing)}"}), 400

    for field in ("player1_licence", "player2_licence"):
        licence = normalise_licence(payload.get(field, ""))
        if not LICENCE_PATTERN.fullmatch(licence):
            return jsonify({"ok": False, "message": f"Licence invalide pour {field}"}), 400

    if normalise_licence(payload.get("player1_licence")) == normalise_licence(payload.get("player2_licence")):
        return jsonify({"ok": False, "message": "Les deux joueurs doivent avoir des licences distinctes."}), 400

    return None


def _check_throttle(ip: str) -> Optional[Response]:
    now = time.time()
    prune_submission_tracker(now)
    history = submission_tracker.setdefault(ip, [])
    if len(history) >= REGISTRATION_CONF.throttle_max_submissions:
        return jsonify({"ok": False, "message": "Trop de tentatives. Veuillez patienter."}), 429
    history.append(now)
    return None


@app.route("/register", methods=["POST"])
def register() -> Response:
    if request.is_json:
        payload = request.get_json() or {}
    else:
        payload = request.form.to_dict()
    validation_error = _validate_payload(payload)
    if validation_error:
        return validation_error

    ip_address = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    throttle_error = _check_throttle(ip_address)
    if throttle_error:
        return throttle_error

    tournament_id = normalise_text(payload.get("tournament_id"))
    licence_one = normalise_licence(payload.get("player1_licence"))
    licence_two = normalise_licence(payload.get("player2_licence"))
    licence_pair = sorted([licence_one, licence_two])

    registrations = load_registrations()
    for row in registrations:
        if normalise_text(row.get("tournament_id")) != tournament_id:
            continue
        existing_pair = sorted([
            normalise_licence(row.get("player1_licence", "")),
            normalise_licence(row.get("player2_licence", "")),
        ])
        if existing_pair == licence_pair:
            logger.info("Duplicate registration blocked for %s (%s, %s)", tournament_id, licence_one, licence_two)
            return jsonify({"ok": False, "message": "Cette équipe est déjà inscrite."}), 409

    confirmed_registrations = [row for row in registrations if normalise_text(row.get("tournament_id")) == tournament_id and normalise_text(row.get("notes")) != "WAITLIST"]
    is_waitlist = False
    if REGISTRATION_CONF.max_teams_per_tournament is not None and len(confirmed_registrations) >= REGISTRATION_CONF.max_teams_per_tournament:
        is_waitlist = True

    timestamp = datetime.utcnow().isoformat(timespec="seconds")
    notes = normalise_text(payload.get("notes"))
    if is_waitlist:
        notes = "WAITLIST"

    row = {
        "timestamp": timestamp,
        "tournament_id": tournament_id,
        "tournament_date": normalise_text(payload.get("tournament_date")),
        "tournament_title": normalise_text(payload.get("tournament_title")),
        "tournament_url": normalise_text(payload.get("tournament_url")),
        "club": normalise_text(payload.get("club")),
        "sex": normalise_text(payload.get("sex")),
        "category": normalise_text(payload.get("category")),
        "player1_name": normalise_text(payload.get("player1_name")),
        "player1_licence": licence_one,
        "player1_phone": normalise_text(payload.get("player1_phone")),
        "player1_email": normalise_text(payload.get("player1_email")),
        "player2_name": normalise_text(payload.get("player2_name")),
        "player2_licence": licence_two,
        "player2_phone": normalise_text(payload.get("player2_phone")),
        "player2_email": normalise_text(payload.get("player2_email")),
        "notes": notes,
        "source_ip": ip_address,
    }

    write_registration_row(row)
    logger.info(
        "Registration stored for %s (%s / %s)%s",
        tournament_id,
        licence_one,
        licence_two,
        " [WAITLIST]" if is_waitlist else "",
    )

    message = "Équipe ajoutée en file d'attente." if is_waitlist else "Inscription enregistrée."
    status_code = 429 if is_waitlist else 201
    return jsonify({"ok": True, "message": message, "waitlist": is_waitlist}), status_code


@app.route("/registrations.csv")
def registrations_csv() -> Response:
    ensure_registration_file()
    return send_file(
        REGISTRATIONS_PATH,
        mimetype="text/csv",
        as_attachment=True,
        download_name="registrations.csv",
        max_age=0,
    )


def _load_club_registrations(club_slug: str) -> List[Dict[str, str]]:
    registrations = load_registrations()
    result = []
    for row in registrations:
        if normalise_club(row.get("club", "")) == club_slug:
            result.append(row)
    return result


@app.route("/club/<token>")
def club_view(token: str) -> str:
    club_token = CLUB_TOKENS.get(token)
    if not club_token:
        abort(404)
    rows = _load_club_registrations(club_token.club_slug)
    return render_template("club.html", club=club_token, registrations=rows)


@app.route("/club/<token>/registrations.csv")
def club_registrations_csv(token: str) -> Response:
    club_token = CLUB_TOKENS.get(token)
    if not club_token:
        abort(404)
    rows = _load_club_registrations(club_token.club_slug)

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=registrations_{club_token.label.replace(' ', '_')}.csv"},
    )


if __name__ == "__main__":
    app.run(debug=True)
