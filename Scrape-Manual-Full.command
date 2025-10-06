#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/scrape.log") 2>&1

[ -d ".venv" ] && source .venv/bin/activate

echo "🟢 Scraping semi-auto + import DB"
python -m services.manual_scrape

echo "✅ Terminé — les tournois sont à jour dans l’app"
