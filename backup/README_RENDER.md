# Deploy to Render — 7 retrained models replacement endpoint

This patch adds two authenticated FastAPI endpoints **without modifying the existing leagues.json or model files**:

- `POST /admin/models/replace-seven-1-6-1`
- `POST /admin/models/rollback-seven-1-6-1`

## Before you start

- This patch is based on the latest supplied FastAPI `app/main.py` plus the previously prepared concurrency improvements. If your deployed `app/main.py` has newer edits, merge the changes instead of overwriting newer code.
- The local archive `Prix_7_Leagues_SKLEARN_1_6_1_RETRAINED.zip` is **not** inside this code patch. You upload it using Postman only after the new API route exists.
- Back up the current FastAPI app and the seven original model directories; pause scheduled prediction jobs and use one API worker during replacement.

## Deploy code to Render (this fixes HTTP 404)

1. Unzip the patch **locally**. Copy **`app/main.py`** and **`app/candidate_replacement.py`** into the `app/` directory of the source repository connected to your Render web service (or merge `main.py` if your code has diverged). Do **not** put them inside `/var/data/prix-models/`—that is a model-data directory, not the running Python source.
2. Commit and push to the Git branch Render deploys, or redeploy the updated code by your normal Render deployment mechanism. Uploading this ZIP using Postman or placing it on the persistent disk will **not** register the route.
3. Confirm the Render deploy is successful. Ensure the process runs the intended module (`uvicorn app.main:app`, or equivalent). Restart/redeploy the service.
4. In Postman run `GET https://YOUR-RENDER-SERVICE/openapi.json` and search for `/admin/models/replace-seven-1-6-1`. If absent, Render is still running other code or another app module. **Do not attempt the replacement until the route appears.**
5. Optionally run the included `verify_route.py` from your FastAPI project root before deploying. It validates route registration locally using the project dependencies without accessing live models.

## Replace the seven model folders

1. Import the included `Prix_7_Retrained_Models_Safe_Replace_Postman.json` collection and set `base_url` and `api_key` in Postman (never paste the key in chat).
2. Check `GET /registry/status`: expect `registry_entries=67`, `enabled_distinct_leagues=55`, `missing_model_folders=[]`, `registry_errors=[]`.
3. In `POST /admin/models/replace-seven-1-6-1`, Headers: `X-API-Key`, `Content-Type: application/zip`; Body > binary, pick **the original** `Prix_7_Leagues_SKLEARN_1_6_1_RETRAINED.zip` (about 46 MB). The endpoint accepts ONLY its validated SHA-256 digest.
4. Response should include `replaced_count: 7`, a `backup_id`, `registry_untouched: true`. Save the `backup_id` privately.
5. Restart Render to clear in-memory model caches, then check `GET /registry/status` still reports 67 entries and none missing. Test loading the Women's Champions League first, then a real fixture. Review-only markets remain review-only.

## If it fails

- **404**: endpoint absent on live Render source; inspect `/openapi.json`, start command, service URL, and current Git commit.
- **401/403**: API key or authorization header incorrect.
- **413**: upload exceeds configured size limit (do not upload the whole training bundle).
- **415**: Body must be raw binary ZIP, with Content-Type `application/zip`.
- **422**: read `detail`—version, free disk, registry mismatch, duplicate replacement, archive checksum, or file validation. No deliberate overwrite happens until preflight succeeds.
- **503**: prediction lock busy; pause other jobs and retry only when idle.

For rollback, pause jobs and POST `/admin/models/rollback-seven-1-6-1` with JSON `{"backup_id":"BACKUP_ID_FROM_SUCCESSFUL_REPLACE"}` then restart Render. Do not run rollback unless recovery is needed.

**Scope**: The new deployment code changes only `app/main.py` and adds `app/candidate_replacement.py`; it does not modify Laravel, payment processing, confidence tiers, or the registry. The trained models are still candidate/review-only; replacing models will not automatically publish picks.
