#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/repair.log") 2>&1

[ -d ".venv" ] && source .venv/bin/activate

python -m tools.repair_db
