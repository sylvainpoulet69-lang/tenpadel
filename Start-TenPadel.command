#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "🚀 Starting TenPadel..."

if [ ! -d ".venv" ]; then
  /usr/bin/python3 -m venv .venv
fi
source .venv/bin/activate

pip install --upgrade pip >/dev/null 2>&1
pip install -r requirements.txt >/dev/null 2>&1
python -m playwright install chromium >/dev/null 2>&1

mkdir -p data data/logs
touch data/app.db
chmod -R u+rwX,go+rwX data

python app.py
