#!/bin/bash
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate

TOKEN=$(jq -r '.admin_token' config.json 2>/dev/null || echo "test")

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

echo "✅ Scraping terminé."
