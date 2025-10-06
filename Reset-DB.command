#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
rm -f data/app.db
echo "🧹 Base supprimée (data/app.db). Elle sera recréée au prochain import."
