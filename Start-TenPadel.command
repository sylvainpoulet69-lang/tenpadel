#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")" || exit 1

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/server.log") 2>&1

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

mkdir -p data "$LOG_DIR"
touch data/app.db
ensure_schema_py='from services.db_import import ensure_schema; ensure_schema()'
python - <<PY
$ensure_schema_py
PY

touch data/tournaments.json
chmod -R u+rwX,go+rwX data

python app.py
