#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")" || exit 1

echo "🎾 Scraping TenUp (module Python)…"

PY="/usr/local/bin/python3"
[ -x "$PY" ] || PY="python3"
if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
fi
source .venv/bin/activate

pip install --upgrade pip setuptools wheel >/dev/null
pip install -r requirements.txt >/dev/null
python -m playwright install chromium >/dev/null 2>&1 || true

export PYTHONPATH="$PWD"

python -m scrapers.tenup && echo "✅ Scrape Python OK" || { echo "❌ Scrape Python KO"; exit 1; }

echo "💾 Vérifie data/tournaments.json"
