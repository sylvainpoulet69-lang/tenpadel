#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d ".venv" ] && source .venv/bin/activate
./Start-TenPadel.command &
sleep 2
./Open-App.command
