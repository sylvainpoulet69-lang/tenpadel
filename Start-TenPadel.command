#!/bin/bash
set -e
cd "$(dirname "$0")" || exit 1
echo "🚀 Starting TenPadel…"

# 1) venv
if [ ! -d ".venv" ]; then
  /usr/bin/python3 -m venv .venv || python3 -m venv .venv
fi
source .venv/bin/activate

# 2) deps visibles
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# 3) playwright
python -m playwright install chromium

# 4) data
mkdir -p data data/logs
touch data/app.db
chmod -R u+rwX,go+rwX data

# 5) démarrer
python app.py
