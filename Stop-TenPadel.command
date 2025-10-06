#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/server.log") 2>&1

echo "🛑 Stopping TenPadel…"
PIDS=$(pgrep -f "[p]ython.*app.py" || true)
if [ -z "$PIDS" ]; then
  echo "Aucun serveur TenPadel actif."
  exit 0
fi

for pid in $PIDS; do
  echo "→ kill $pid"
  kill "$pid" || true
done

echo "✅ Stop demandé."
