# PrixPredictor Production Rolling-Window Patch

## Architecture retained

- FastAPI owns FootyStats synchronization, feature construction, model execution, explainability, and `ticket_eligible` decisions.
- Laravel imports eligible candidates, stores them, packages standalone tickets, packages parallel cross-league tickets from the complete pool, publishes tickets, and groups them by fixture date.
- Cross-league packaging is always attempted. It is not restricted to weak leagues or unused standalone candidates.

## Registry

The supplied registry contains 28 canonical leagues and 12 aliases. The active test expectation was corrected from 29 to 28. Alias entries remain available for route compatibility but are excluded from canonical batch execution.

Registry model-version metadata was normalized to `{canonical_slug}-v0.6.4-explainable`. Runtime model configuration inside each model folder remains the final source of truth.

## FastAPI changes

- Preserved the corrected exact FootyStats status handling (`incomplete` is not completed).
- Added `PRIX_MAX_PREDICTION_WINDOW_DAYS`, default 7.
- `/predict/eligible` now rejects oversized date windows before loading models or calling FootyStats.
- `/models` now requires `X-API-Key`.
- Updated the active-league test runner:
  - Expects 28 canonical leagues.
  - Supports `--days 3` for today through today + 3.
  - Verifies every eligible candidate is inside the requested date range.
  - Verifies active markets, explainability fields, feature quality, and unique candidate identities.
- Added regression tests for alias exclusion and date-window limits.
- Included the corrected `models/leagues.json` but no production model binaries.

## Laravel changes

### Rolling date windows

The command now supports:

```bash
php artisan prix:generate-tickets
php artisan prix:generate-tickets --days=3
php artisan prix:generate-tickets --from=2026-07-18 --to=2026-07-21
php artisan prix:generate-tickets 2026-07-18 --days=3
php artisan prix:generate-tickets --days=0 --force
```

`--days=3` means the start date plus the next three days, inclusive.

### Production scheduler

Default schedule in `app/Console/Kernel.php`:

- 02:00: all active leagues, today through today + 3.
- 07:00: same-day refresh.
- Every two hours from 06:15 through 22:15: same-day refresh.
- Every 30 minutes: ticket settlement.

All times use `Africa/Nairobi` by default.

### Safe partial failures

Previously, candidates could be archived for a league even when that league failed during the API batch. Candidate retirement is now restricted to league summaries that completed safely (`healthy`, `low_volume`, or `no_fixtures`).

Statuses such as `failed`, `model_unavailable`, `feature_failure`, and `stale_season` preserve the last valid candidate snapshot and published tickets.

Candidate retirement and new candidate upserts now run in one database transaction.

### Cross-league packaging

For each date and tier, Laravel independently builds:

1. Standalone tickets grouped by league.
2. Cross-league tickets from the complete eligible tier pool.

A candidate can appear once in a standalone ticket and once in a cross-league ticket. Inside a single ticket Laravel still enforces:

- one prediction per fixture;
- at least two leagues for cross-league packages;
- maximum one Match Outcome selection;
- active candidate markets only;
- configured confidence, risk, data-quality, and tier rules.

### Admin and auditing

- Admin generation now supports Today, Today + 1, or Today + 3.
- Generation runs now record trigger source, force-refresh state, and requested window days.
- The Laravel live test command supports `--days` and validates candidate response rules.

## Database

Use one of the following, not both:

```bash
php artisan migrate --force
```

or run:

```text
PrixPredictor_production_window_patch.sql
```

The complete patched dump is:

```text
mirightc_prixpredictor_production_patched.sql
```

## Environment additions

### FastAPI

```env
PRIX_MAX_PREDICTION_WINDOW_DAYS=7
```

### Laravel

```env
PRIX_EXPECTED_CANONICAL_LEAGUES=28
PRIX_DEFAULT_WINDOW_DAYS=3
PRIX_MAX_WINDOW_DAYS=7
PRIX_SYNC_ROLLING_TIME=02:00
PRIX_SYNC_MORNING_TIME=07:00
PRIX_SYNC_SAME_DAY_CRON="15 6-22/2 * * *"
PRIX_SCHEDULE_ON_ONE_SERVER=false
PRIX_SCHEDULE_IN_BACKGROUND=false
```

For multiple production web servers using a shared supported cache driver, set:

```env
PRIX_SCHEDULE_ON_ONE_SERVER=true
```

`PRIX_SCHEDULE_IN_BACKGROUND` should be enabled only after confirming the production shell supports Laravel background commands.

## Local testing

### FastAPI

```powershell
pytest -q
python scripts/v064_active_leagues_test.py --skip-live
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second PowerShell window:

```powershell
python scripts/v064_active_leagues_test.py `
  --date 2026-07-18 `
  --days 3 `
  --api-url "http://127.0.0.1:8000" `
  --api-key "YOUR_LOCAL_KEY" `
  --force
```

### Laravel

```powershell
php artisan migrate
php artisan optimize:clear
php artisan prix:test-active-leagues 2026-07-18 --days=3 --force
php artisan prix:generate-tickets 2026-07-18 --days=3 --force
php artisan schedule:list
```

For local scheduler testing:

```powershell
php artisan schedule:work
```

For production Linux cron:

```cron
* * * * * cd /path/to/laravel && php artisan schedule:run >> /dev/null 2>&1
```

## Validation completed

- FastAPI app, scripts, and tests compile.
- 9 tests passed with no mounted model folders; model-dependent tests skipped as expected.
- 13 tests passed using the Latvia v0.6.4 model bundle.
- Latvia model warnings in this build environment were only because the runner has scikit-learn 1.8.0. Production requirements remain pinned to 1.6.1.
- Registry validation: 28 canonical leagues, 12 aliases, zero structural errors.
- All 768 PHP files in the canonical Laravel package passed `php -l`.
