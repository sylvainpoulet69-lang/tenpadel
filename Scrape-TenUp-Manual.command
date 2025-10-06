#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# active venv
if [ -d ".venv" ]; then source .venv/bin/activate; fi
echo "🟢 Scraping TenUp (mode semi-auto) — services.manual_scrape"
python -m services.manual_scrape
