# Prix Predictor — scoped deployment patch (10 Nov 2026)

This patch is based on the previously attached `priapp.zip` with the previously approved Stripe Checkout parameter fix and international-competition Laravel changes, plus `FastApiCurrent.zip` with the previously approved seven-league FastAPI integration patch.

## Contents / behavior
- Admin Prediction Tickets form: Today; Tomorrow (day AFTER selected start date); Next 2,3,4,5,6,7 days (inclusive of chosen start date).
- Searchable, checkable league selector with Run all or selected-only mode. Includes an individual league count, search-results bulk select, and clear.
- Selected league slugs persisted in the existing `prix_ticket_generation_jobs.summary_json` field; **no database migration**.
- CLI scheduler and admin browser worker both honor the selection. Existing scheduled jobs with no selection continue to process all active leagues.
- Safe bounded retry/backoff of only HTTP 429/503 for prediction requests; shorter Laravel inter-worker lock wait, to avoid long blocked PHP requests. FastAPI heavy request wait default 10 seconds; setting PRIX_HEAVY_REQUEST_WAIT_SECONDS can override it.
- League diagnostic logs for fixture counts, feature rows, eligible candidates, statuses, errors; explicit review-only warning if candidates but no eligible selections.
- Registry slug mapping keeps API slugs separate from model folder names, including UCL/UECL/USA/Northern Ireland aliases.
- Stripe: idempotency key on identical Checkout Session requests; safe event/status logs and retry of signed webhook events that reference a transaction not yet available. **No pricing, charge, or provider changes.**
- Existing repackage action retains its old `days` input semantics even with the new generation window form.
- International league registry integration from previous patch included in Laravel patch.

## Deploy (file-for-file; do NOT delete anything else)
1. Back up the current Laravel files listed below. Do not upload `.env`, vendor directories, model directories, or SQL databases from this patch.
2. On the Laravel host, place the contents of the Laravel ZIP into the Laravel root, keeping relative paths. `app/...`, `resources/views/admin/...`, and `config/prix_model.php` should land at their matching paths.
3. On the Render/FastAPI service, replace ONLY `app/main.py` and `app/config.py` from the FastAPI ZIP. It assumes the previously approved seven-league FastAPI integration files are already deployed.
4. Run Laravel: `php artisan optimize:clear`; run `php artisan config:cache` only if production already uses it. Restart Laravel workers/cron processes as applicable. Restart/redeploy Render service.
5. In `/admin/tickets`, pick Tomorrow or Next 2-7 days, choose all or selected, generate. Monitor league-by-league progress and generation history.
6. Verify Render logs include `prediction_league_result` per league and Laravel includes `Prix ticket league diagnostic`. A model may produce candidates with zero ticket-eligible picks if its markets are still `review_only` or quality criteria are unmet.
7. In Stripe test mode, verify creation -> webhook -> access, and repeat an identical Checkout initiation to validate Stripe idempotency. Never consider a return URL proof of payment.

## Environment notes
- Laravel: `PRIX_GENERATION_BUSY_RETRIES=3` (defaults to 3, capped at 4), `PRIX_HEAVY_LOCK_WAIT_SECONDS=3` (defaults to 3 seconds). Note: the existing PHP browser worker overrides retries to 1 per HTTP step, and schedules next attempts independently.
- FastAPI: `PRIX_HEAVY_REQUEST_WAIT_SECONDS` if already configured overrides its new 10-second default.
- Existing `PRIX_MAX_WINDOW_DAYS` must be at least 7 to enable the 7-day option. Default is 7.
- The seven model folders and `leagues.json` already on the API server remain unchanged. The patch does NOT force model markets out of `review_only` or modify confidence rules.

## Testing performed
- `php -l` on all modified PHP source files.
- Node `--check` on extracted admin page JavaScript (Blade route expressions replaced with constants during syntax-only check).
- `python -m py_compile` on changed FastAPI modules, and FastAPI import/route check.
- PHP canonical slug mapping smoke test.
- **Not tested:** live Stripe transactions/webhooks, actual FootyStats requests, real production database/queue/cron, production Render concurrency or end-to-end paid ticket activation.

## Rolling back
Back up the original files before overwriting. To roll back, restore those same files, run `php artisan optimize:clear`, and redeploy the previous Render version. This patch does not migrate data or overwrite models, but queued jobs already started may contain selected scopes; cancel an in-progress job before downgrading.
