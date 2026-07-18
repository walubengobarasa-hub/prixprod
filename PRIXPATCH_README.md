# PrixPredictor FastAPI v0.6.4 patch

## Purpose

FastAPI owns FootyStats synchronization, pre-match feature construction, model loading, prediction generation, explainability, and candidate eligibility. It returns a unified eligible-candidate pool to Laravel. Ticket packaging is intentionally disabled in FastAPI because Laravel is now the only packaging and publication authority.

## Required layout

```text
app/
models/
  leagues.json
  epl/
  spain/
  ...all 29 canonical league folders...
data/cache/
scripts/
tests/
```

Each league folder must use the same v0.6.4 structure as the Latvia sample and contain every artifact referenced by `model_config.json`.

## Environment

Copy `.env.example` to `.env` and set real values:

```env
APP_ENV=production
APP_DEBUG=false
PRIX_MODEL_API_KEY=use-the-same-long-random-key-as-laravel
FOOTYSTATS_API_KEY=your-footystats-key
MODEL_ROOT=models
CACHE_ROOT=data/cache
CACHE_TTL_SECONDS=3600
FOOTYSTATS_TIMEOUT_SECONDS=45
MINIMUM_FEATURE_COVERAGE=0.15
MINIMUM_TEAM_HISTORY=3
MAXIMUM_SEASON_STALENESS_DAYS=370
PLATFORM_TIMEZONE=Africa/Nairobi
PRIX_MAX_CACHED_LEAGUE_MODELS=3
```

Keep `scikit-learn==1.6.1`. The uploaded v0.6.4 artifacts were trained with that version.

## Install and run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use a process manager such as systemd or Supervisor in production. Keep the service private behind Laravel or an internal reverse proxy.

## Current-date validation

From the FastAPI project root:

```bash
python scripts/v064_active_leagues_test.py --force
```

For the current project date explicitly:

```bash
python scripts/v064_active_leagues_test.py --date 2026-07-18 --force
```

Static-only model and registry validation:

```bash
python scripts/v064_active_leagues_test.py --skip-live
pytest -q
```

The test discovers every enabled canonical league in `models/leagues.json`, requires at least 29, loads every referenced model with `joblib.load()`, checks the 400-feature contract, calls `/predict/eligible`, detects stale seasons, checks non-zero feature coverage, and verifies candidate/explanation rules.

## Main API contract

```http
POST /predict/eligible
X-API-Key: <PRIX_MODEL_API_KEY>
Content-Type: application/json
```

```json
{
  "leagues": ["epl", "spain", "latvia"],
  "date_from": "2026-07-18",
  "date_to": "2026-07-18",
  "force_refresh": true,
  "include_ineligible": false
}
```

FastAPI returns eligible candidates, league health summaries, contract versions, and a generation run ID. `tickets` are not produced by FastAPI.

## Cache reset

```bash
rm -f data/cache/live_*
rm -f data/cache/footystats_league_matches_*
```

A force-refresh request normally removes the need for manual deletion.
