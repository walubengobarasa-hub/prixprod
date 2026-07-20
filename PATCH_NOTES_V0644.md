# PrixPredictor v0.6.4.4

## Laravel

- Saves eligible and ineligible candidates from each generation run.
- Ineligible candidates remain excluded from ticket packaging.
- Adds `/admin/candidates/ineligible` with date, league, market and review-status filters.
- Adds review states: new, reviewed, watchlist, dismissed and archived.
- Limits frontend league filters to six active leagues. Each league opens its filtered ticket view.
- Adds automatic fixture-result checks after the final scheduled match on each ticket.
- Grades Double Chance, Over 1.5 and Match Outcome selections.
- Voids postponed or cancelled fixtures.
- Updates ticket item scores, ticket accuracy and ticket status.
- Adds an AJAX `Check Results` action on the Tickets page.
- Admin ticket table and frontend ticket cards refresh result states.
- Scheduler checks results every 15 minutes.

## FastAPI

- Adds authenticated `POST /results/fixtures`.
- Accepts FootyStats match IDs and canonical league slugs.
- Returns completed, pending, cancelled and not-found fixture states.
- Returns full-time scores, total goals and HOME/DRAW/AWAY outcome.

## Install Laravel

Copy the Laravel ZIP over the current complete Laravel project.

Run either the migration or the standalone SQL patch, not both:

```bash
php artisan migrate --force
php artisan optimize:clear
php artisan config:cache
```

Add to Laravel `.env`:

```env
PRIX_MODEL_RESULTS_ENDPOINT=/results/fixtures
PRIX_RESULT_CHECK_DELAY_MINUTES=120
PRIX_RESULT_FORCE_REFRESH=true
```

The server cron must run Laravel Scheduler every minute:

```cron
* * * * * cd /path/to/prixpredictor && php artisan schedule:run >> /dev/null 2>&1
```

## Deploy FastAPI

Copy the FastAPI ZIP over the Render API source while retaining:

- `.env`
- `models/leagues.json`
- all league model folders

Redeploy and test:

```powershell
$headers = @{ "X-API-Key" = "YOUR_KEY" }
$body = @{
  fixtures = @(
    @{ match_external_id = "8468209"; league_slug = "latvia" }
  )
  force_refresh = $true
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "https://prixai.onrender.com/results/fixtures" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

## Test Laravel

```bash
php artisan prix:generate-tickets --days=3 --force
php artisan prediction:sync-results --force
php artisan schedule:list
```

Manual tickets require the FootyStats match ID for each selection.
