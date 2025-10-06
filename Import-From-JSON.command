#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d ".venv" ] && source .venv/bin/activate
python -m services.import_from_json
