#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d ".venv" ] && source .venv/bin/activate
echo "🟢 Scraping semi-auto + import DB"
python -m services.manual_scrape
echo "✅ Terminé — les tournois sont à jour dans l’app"
