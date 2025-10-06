#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d ".venv" ] && source .venv/bin/activate
echo "🟢 Scrape manuel puis healthcheck"
python -m services.manual_scrape
python -m tools.healthcheck
