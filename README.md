# Ten Padel – Calendrier & Inscriptions

Application Flask qui agrège les tournois Padel TenUp, propose un calendrier filtrable et recueille les inscriptions d'équipes.

## Structure

```
padel-mvp/
├── app.py                  # Application Flask + API REST
├── fetch_auto.py           # Scraper Playwright TenUp
├── config.json             # Paramètres scraping + règles d'inscription
├── templates/
│   ├── index.html          # Calendrier public + formulaire modal
│   └── club.html           # Vue filtrée pour les clubs
├── static/
│   └── style.css           # Styles globaux (UI calendrier / modal)
└── data/
    ├── tournaments.json    # Tournois consolidés (scraper)
    ├── registrations.csv   # Inscriptions équipes (export)
    ├── snapshot.html       # Snapshot TenUp (audit)
    └── storage_state.json  # État Playwright
```

## Prérequis

- Python 3.11+
- Dépendances Python : `flask`, `playwright` (+ `playwright install chromium`)

## Scraping TenUp

```bash
python fetch_auto.py
```

Le script lit `config.json`, suit la pagination « Suivant », convertit les URL relatives en absolues, détecte la catégorie (P25…P2000) et le sexe (DM/DD/DX), et calcule un `tournament_id` stable (SHA-1 de l'URL). Les résultats sont dédoublonnés et écrits dans `data/tournaments.json`.

## Lancement de l'app

```bash
python app.py
```

Endpoints :

- `GET /` : calendrier + liste filtrable.
- `GET /api/tournaments` : JSON des tournois.
- `POST /register` : enregistre une équipe (anti-doublons, limite par tournoi, throttling IP).
- `GET /registrations.csv` : export global.
- `GET /club/<token>` : vue filtrée club (token → `config.json`).
- `GET /club/<token>/registrations.csv` : export CSV filtré.

## Configuration

`config.json` centralise les options :

- `tenup.*` : paramètres Playwright (URL, headless, scroll…).
- `registration.*` : limite d'équipes, regex licence, throttling IP.
- `club_tokens` : tokens → { `club_slug`, `label` } pour la vue club.

## Données

- `data/tournaments.json` : format conforme au cahier des charges (date ISO + `date_text`).
- `data/registrations.csv` : colonnes complètes (tournoi, joueurs 1 & 2, notes, IP).

Le formulaire modal impose 2 licences valides (`^[A-Z0-9]{6,12}$` par défaut), au moins un téléphone et applique les validations côté client + serveur.
