# Prix Predictor FastAPI registry diagnostics (non-destructive)

## Verified from supplied source
- `/health` registered_leagues is len(league_registry.enabled_slugs()); it does not count model artifacts.
- Registry is read from model_root_path()/leagues.json on startup and on POST /registry/reload.
- `/predict/eligible` processes leagues sequentially. HTTP requests to FootyStats may take up to 45 seconds each.
- Your supplied leagues(2).json has 60 enabled keys, including 12 aliases => 48 distinct leagues.

## Deploy
1. Back up app/main.py.
2. Merge supplied app/main.py into the deployed FastAPI app (same version as supplied FastApi(1).zip).
3. Restart the FastAPI server to load the route. Keep your real secrets in environment variables.
4. GET /registry/status with the same API key as other protected API endpoints (header according to app/security.py). DO NOT paste the key into chat.
5. Compare model_root, registry_path, registered_slugs and missing_model_folders.
6. Ensure current leagues.json and corresponding model directories exist in the reported model_root. Only then POST /registry/reload and check 48 expected distinct leagues.

## 502 protection / next backend patch
- Laravel should batch `/predict/eligible` requests into ~3–5 registered leagues each, and handle each batch's failure separately. This requires the CURRENT app/Services/PrixModelApiService.php to patch safely; not included in the uploaded FastAPI ZIP.
- For result sync, group requests into similarly bounded league chunks; run in queues or scheduled jobs rather than blocking web page responses.
- Do not simply increase HTTP timeouts to huge values, or automatically treat unresolved fixture results as losses.
- Confirm both /predict/eligible and /results/fixtures with a SINGLE league before testing multiple leagues.
- Cup model config should be checked for model_family agreement: the supplied registry uses `cup` which loader checks strictly against model_config.json.
