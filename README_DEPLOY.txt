# Prix Predictor FastAPI — registry and provider error patch (2026-11-02)

Incremental files built on `appapi.zip` plus the earlier low-memory patch. Preserve your already-installed FastAPI low-memory configuration and deployed model files.

## Changes
- Updated supplied approved `models/leagues.json`: UEFA Champions League and Conference League have competition_type=`cup` but model_family=`main_league`, matching `ucl/model_config.json` and `uecl/model_config.json`; aligned four artifact model_version keys (`northern_ireland`, `usa`, `ucl`, `uecl`). No model retraining.
- `GET /registry/diagnostics` (requires your existing X-API-Key) provides cheap per-league manifest/model-folder/season/family checks **without** loading trained sklearn models or calling FootyStats.
- `footystats_client` rejects upstream HTTP-200 error envelopes and malformed `league-matches` responses instead of silently treating them as no fixtures; errors surface in per-league `league_summaries`.

## Deployment important for Render persistent model storage
1. Upload `app/main.py` and `app/footystats_client.py` to the current FastAPI repo, preserving the low-memory patch.
2. Put `models/leagues.json` in the **actual active model directory**. If Render `MODEL_ROOT` points to a persistent disk (e.g. `/var/data/models`), replacing only the repository's `models/leagues.json` may NOT update the persistent copy. Safely copy the approved registry to that active path or use your current deployment workflow.
3. Do not delete existing trained model directories. This package intentionally includes only the registry JSON, not 48 model bundles.
4. Restart/redeploy `prixmodel`, verify `/health` and authenticated `/registry/diagnostics` for all enabled model folders. Confirm UEFA competition models report `registered`.
5. Deploy the Laravel patch. Do not send your API key in chat or browser query strings.

If UCL still reports missing after deploying: verify `MODEL_ROOT` in the diagnostic response and that the deployed runtime contains both `models/leagues.json` and `models/ucl/model_config.json`. The supplied source packages alone cannot verify the files actually mounted on Render.
