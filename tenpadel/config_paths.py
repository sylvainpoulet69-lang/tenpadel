"""Centralised filesystem paths for the TenPadel project."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "app.db"
JSON_PATH = DATA / "tournaments.json"
LOG_DIR = DATA / "logs"

__all__ = ["ROOT", "DATA", "DB_PATH", "JSON_PATH", "LOG_DIR"]
