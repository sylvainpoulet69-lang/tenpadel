# Rapport de maintenance TenPadel

## Fichiers supprimés

- `fetch_auto.py`
- `fetch_paginated.py`

## Fichiers conservés et vérifiés

- `services/scrape.py`
- `services/manual_scrape.py`
- `scrapers/tenup.py`
- Scripts `.command` (Start, Stop, Open, Scrape auto, Scrape manuel, Scrape module)
- `requirements.txt` (mise à jour pour inclure SQLAlchemy)

## Scripts testés

- `./Start-TenPadel.command` — échec dans cet environnement à cause du proxy réseau qui empêche `pip install` (erreur 403).
- `./Scrape-TenUp-Manual.command` — échec pour la même raison (impossible d’installer les dépendances).

> Les commandes se lancent correctement mais les installations réseau échouent sur cette plateforme. Sur une machine disposant d’un accès internet direct, elles doivent aboutir.

