#!/bin/bash
set -e
cd "$(dirname "$0")" || exit 1

# Token admin
if command -v jq >/dev/null 2>&1; then
  TOKEN=$(jq -r '.admin_token' config.json)
else
  TOKEN=$(python3 - <<'PY'
import json,sys
try:
    print(json.load(open("config.json"))["admin_token"])
except Exception:
    print("test")
PY
)
fi

# App doit tourner
curl -sf "http://127.0.0.1:5000/" >/dev/null || {
  echo "❌ L'app ne tourne pas. Lance Start-TenPadel.command d'abord."
  exit 1
}

# Scrape
curl -X POST "http://127.0.0.1:5000/admin/scrape" \
  -H "Content-Type: application/json" \
  -H "X-ADMIN-TOKEN: $TOKEN" \
  -d '{
        "categories": ["H","F","MIXTE"],
        "date_from": "2025-10-01",
        "date_to":   "2025-12-31",
        "region":    "PACA",
        "level":     ["P250","P500"],
        "limit":     100
      }'
echo
echo "✅ Scraping terminé."
