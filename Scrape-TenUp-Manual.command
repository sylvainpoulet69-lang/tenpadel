#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")" || exit 1

echo "🎾 Scraping TenUp (mode manuel)…"

PY="/usr/local/bin/python3"; [ -x "$PY" ] || PY="python3"
[ -d ".venv" ] || "$PY" -m venv .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel >/dev/null
pip install -r requirements.txt >/dev/null
python -m playwright install chromium >/dev/null 2>&1 || true

mkdir -p data data/logs
chmod -R u+rwX,go+rwX data

touch data/app.db

export PYTHONPATH="$PWD"
echo "➡️  python -m services.manual_scrape"
python -m services.manual_scrape

if [ -s "data/tournaments.json" ]; then
  echo "✅ Scraping ok → data/tournaments.json"
else
  echo "⚠️ Scraping terminé, pas de tournaments.json"
fi
