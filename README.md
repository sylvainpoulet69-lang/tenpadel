# Tenpadel – agrégateur TenUp Padel

Application Flask centralisant les tournois de padel TenUp :

* Scraper Playwright/HTTP (`scrapers/tenup.py`) produisant un modèle normalisé `Tournament` (Pydantic).
* Persistance SQLite via SQLAlchemy (`data/app.db`) avec export JSON miroir (`data/tournaments.json`).
* API REST + interface web pour explorer les tournois, gérer les filtres (catégorie, période, zone, niveau) et déclencher un scraping administrateur.
* Module d’inscription existant conservé (CSV) avec modal côté front.

## Structure du projet

```
tenpadel/
├── app.py                        # Application Flask principale
├── api/
│   └── tournaments.py           # API REST /api/tournaments
├── extensions.py                # Instances partagées (SQLAlchemy)
├── models/
│   └── tournament.py            # Modèle Pydantic normalisé
├── scrapers/
│   └── tenup.py                 # Scraper TenUp (Playwright + CLI)
├── services/
│   ├── scrape.py                # Orchestration scraping
│   ├── tournament_store.py      # Upsert + export JSON
│   └── tournament_store_models.py
├── templates/
│   ├── index.html               # UI publique (filtres + admin refresh)
│   └── club.html                # Vue club existante
├── static/style.css             # Styles UI
├── data/
│   ├── app.db                   # Base SQLite
│   ├── tournaments.json         # Export JSON pour le front
│   ├── registrations.csv        # Inscriptions équipes
│   ├── logs/tenup.log           # Logs scraper (rotation)
│   └── errors/                  # Captures Playwright (si erreur)
├── config.json                  # Configuration globale
└── requirements.txt             # Dépendances Python
```

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install
```

## Lancer l’application

```bash
python app.py
```

* L’API `/api/tournaments` fournit des paramètres `category`, `from`, `to`, `region`, `city`, `radius_km`, `level`, `limit`, `page`, `sort`.
* La page `/` consomme l’API et propose :
  - filtres catégorie (Tous/H/F/Mixte), période, région/ville/rayon, niveaux P25→P1000.
  - calendrier interactif + cartes avec statut d’inscription et accès direct TenUp.
  - bouton `Rafraîchir (admin)` si `?admin=1` (demande du token pour déclencher `/admin/scrape`).
* Les inscriptions équipes (CSV) fonctionnent comme auparavant via `/register`.

## Scraping TenUp

### Scraping manuel depuis l’API admin

```bash
curl -X POST http://127.0.0.1:5000/admin/scrape \
  -H "Content-Type: application/json" \
  -H "X-ADMIN-TOKEN: <ADMIN_TOKEN>" \
  -d '{
        "categories": ["H", "F", "MIXTE"],
        "date_from": "2025-10-01",
        "date_to": "2025-12-31",
        "region": "PACA",
        "level": ["P250", "P500"],
        "limit": 200
      }'
```

Réponse : `{"ok": true, "inserted": X, "updated": Y, "skipped": Z, "duration_s": 12.3, ...}`.

### CLI `python -m scrapers.tenup`

Mode démonstration (écrit `data/tenup-sample.json`) :

```bash
python -m scrapers.tenup --dry-run \
  --category H --category MIXTE \
  --from 2025-10-01 --to 2025-12-31 \
  --region PACA --limit 50
```

Sans `--dry-run`, les tournois normalisés sont affichés en JSON (stdout).

### Scheduler automatique

`app.py` installe un job APScheduler (`scrape_interval_hours` dans `config.json`, par défaut 6 h). Logs structurés dans `data/logs/tenup.log`.

## Base de données & modèle

* Table `tournaments` (SQLite) : colonnes normalisées du modèle Pydantic + `id`, `created_at`, `updated_at`.
* Contrainte d’unicité `(source, external_id, start_date)` → upsert.
* Export JSON miroir `data/tournaments.json` mis à jour après chaque upsert.

## Configuration (`config.json`)

```json
{
  "tenup": {
    "base_url": "https://tenup.fft.fr/recherche/tournois",
    "headless": true,
    "default_region": "PACA",
    "default_city": "Cagnes-sur-Mer",
    "default_radius_km": 150,
    "request_timeout_ms": 30000,
    "max_results": 500,
    "scrape_interval_hours": 6,
    "respect_rate_limit": true,
    "log_path": "data/logs/tenup.log"
  },
  "admin_token": "CHANGE_ME_STRONG_TOKEN",
  "registration": {
    "max_teams_per_tournament": 64,
    "licence_regex": "^[A-Z0-9]{6,12}$",
    "throttle_window_seconds": 60,
    "throttle_max_submissions": 2
  },
  "club_tokens": {
    "sampletoken123": {
      "club_slug": "ULTRA COUNTRY CLUB",
      "label": "Ultra Country Club"
    }
  }
}
```

## Points clés

* Scraper Playwright + fallback DOM (accepte cookies, applique filtres TenUp, pagine `Charger plus`, dédoublonne).
* Logs rotation 10 Mo x5 (`loguru`), respect rate limit (0.3–0.9 s).
* API Flask-SQLAlchemy (paginée, tri ASC/DESC sur `start_date`).
* Front : badge état inscriptions, lien TenUp, bouton pré-inscription existant, admin refresh.
* CLI/offline : `python -m scrapers.tenup` pour tester ou produire un JSON d’échantillon.
