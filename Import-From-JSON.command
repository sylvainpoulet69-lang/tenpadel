#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi
python - <<'PY'
import json
import sys
from pathlib import Path

from services.db_import import import_items

path = Path("data/tournaments.json")
if not path.exists():
    print("❌ Fichier data/tournaments.json introuvable.", file=sys.stderr)
    sys.exit(1)

content = path.read_text(encoding="utf-8").strip()
if not content:
    tournaments = []
else:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"❌ JSON invalide: {exc}", file=sys.stderr)
        sys.exit(1)
    if isinstance(raw, dict):
        tournaments = raw.get("tournaments")
        if tournaments is None and isinstance(raw.get("items"), list):
            tournaments = raw["items"]
        if tournaments is None:
            tournaments = []
    elif isinstance(raw, list):
        tournaments = raw
    else:
        print("❌ Format JSON inattendu.", file=sys.stderr)
        sys.exit(1)

if not isinstance(tournaments, list):
    print("❌ Le contenu JSON ne contient pas une liste de tournois.", file=sys.stderr)
    sys.exit(1)

inserted = import_items([dict(item) for item in tournaments])
print(f"✅ Import terminé — {inserted} nouvelles lignes ajoutées.")
print(f"ℹ️ Total éléments lus dans le JSON : {len(tournaments)}")
PY
