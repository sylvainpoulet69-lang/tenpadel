#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")" || exit 1
echo "🎾 Scraping TenUp (sans API)…"

PY="/usr/local/bin/python3"; [ -x "$PY" ] || PY="python3"
[ -d ".venv" ] || "$PY" -m venv .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel >/dev/null
pip install -r requirements.txt >/dev/null
python -m playwright install chromium >/dev/null 2>&1 || true

mkdir -p data data/logs
touch data/app.db
chmod -R u+rwX,go+rwX data

export PYTHONPATH="$PWD"
echo "➡️  python -m services.scrape"
python -m services.scrape

if [ -f "data/tournaments.json" ]; then
  echo "✅ Scraping ok → data/tournaments.json"
else
  echo "⚠️ Scraping terminé, pas de tournaments.json"
fi
