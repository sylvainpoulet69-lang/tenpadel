#!/usr/bin/env bash
set -e

# Se placer dans le dossier du script
cd "$(dirname "$0")"

echo "🎾 Scraping TenUp (mode manuel)…"

# Créer venv si absent
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# Activer venv
source .venv/bin/activate

# Mettre pip à jour rapidement (silencieux)
python -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true

# Installer les dépendances
pip install -r requirements.txt

# Installer Chromium pour Playwright
python -m playwright install chromium

# Exposer le projet au PYTHONPATH
export PYTHONPATH="$PWD"

# Lancer le mode manuel
python -m services.manual_scrape
