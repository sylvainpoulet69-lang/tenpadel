#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")" || exit 1

echo "🚀 Starting TenPadel…"

PY="/usr/local/bin/python3"
[ -x "$PY" ] || PY="python3"

if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
fi
source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python -m playwright install chromium

mkdir -p data data/logs
touch data/app.db
touch data/tournaments.json
chmod -R u+rwX,go+rwX data

python app.py
