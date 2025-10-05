#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")" || exit 1

echo "🎾 Scraping TenUp (sans API)…"

PY="/usr/local/bin/python3"
[ -x "$PY" ] || PY="python3"
if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
fi
source .venv/bin/activate

pip install --upgrade pip setuptools wheel >/dev/null
pip install -r requirements.txt >/dev/null
python -m playwright install chromium >/dev/null 2>&1 || true

mkdir -p data data/logs
touch data/app.db
touch data/tournaments.json
chmod -R u+rwX,go+rwX data

export PYTHONPATH="$PWD"

if python - <<'PY'
import importlib.util, sys
spec = importlib.util.find_spec("services.scrape")
sys.exit(0 if spec else 1)
PY
then
  echo "➡️  python -m services.scrape"
  python -m services.scrape
else
  echo "➡️  python -m scrapers.tenup"
  python -m scrapers.tenup
fi

if [ -f "data/tournaments.json" ]; then
  echo "✅ Scraping terminé. Fichier mis à jour : data/tournaments.json"
else
  echo "⚠️ Scraping terminé, mais data/tournaments.json est introuvable."
fi
