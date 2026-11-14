# Prix Predictor — GitHub-to-Render league deployment (additive patch)

This patch is for the **FastAPI service**. It does not change Laravel or your
`/var/data/prix-models` disk until a committed release with real models is
present. It uses the latest trained files you choose to commit, never retrains on Render.

## One-time FastAPI setup

1. **Back up your repository and persistent disk**. Keep the current working
   `leagues.json` (previously 67 entries) and all existing folders.
2. Copy the `app/`, `scripts/`, `deploy_models/` and `examples/` paths into the
   root of your **current** FastAPI repo, without replacing its `app/main.py`.
3. Run once from the repo root:
   `python scripts/enable_git_model_sync.py`
   This inserts two small sections into **your existing** `app/main.py` and
   backs it up locally as `app/main.py.before-git-sync`. Do not commit that backup.
4. Add `app/main.py.before-git-sync` to `.gitignore`.
5. Render environment: `MODEL_ROOT=/var/data/prix-models` (already configured),
   `PRIX_EXPECTED_SKLEARN_VERSION=1.6.1`, and `PRIX_REQUIRE_PERSISTENT_MODEL_ROOT=1`.
   Baseline safety guard: `PRIX_GIT_SYNC_MIN_BASE_ENTRIES=67`
   (already the default; adjust only if your verified live baseline differs). Ensure
   `scikit-learn==1.6.1` remains pinned in the service's requirements.
6. Keep Render's existing start command (normally `uvicorn app.main:app ...`).
   Enable **Auto Deploy** for the GitHub branch. Push this integration once.
7. Verify `GET /registry/git-sync-status` with `X-API-Key`; it should say no
   `deploy_models/leagues.json` is committed yet. Existing 67 entries are untouched.

## Onboarding the six new England leagues (and future batches)

1. Run the provided Colab trainer using `scikit-learn==1.6.1`; download the
   validated **model folders**, not just the report or training sources.
2. Inside the FastAPI repository, create:
   ```
   deploy_models/
     leagues.json                         # new league entries; additions/updates
     models/
       england-championship/
         model_config.json
         model_metadata_v064.json
         ... .pkl and feature columns ...
       england-efl-league-one/
       england-efl-league-two/
       england-national-league/
       england-national-league-north/
       england-national-league-south/
   ```
   Copy the *example* `examples/England_6_leagues.json` to
   `deploy_models/leagues.json` **only together with the actual trained model
   directories**. New source folders must match `model_folder` in JSON.
3. Preflight locally in an environment using the same scikit-learn version:
   `python -m app.git_model_sync --repo . --disk /path/to/copy-of-model-disk --dry-run`
   Never run it against production disk from a developer machine.
4. Commit the model files and JSON to GitHub; Render redeploys. **At process
   startup** the sync validates artifacts/sklearn/FootyStats IDs, stages files,
   installs missing folders, then merges new entries into the persistent
   `leagues.json` atomically. If validation fails, startup fails rather than
   serving a partially applied registry.
5. Verify with Postman (read-only requests):
   - `GET https://<render-host>/registry/git-sync-status`
   - `GET https://<render-host>/registry/status`
   Both require `X-API-Key: <PRIX_MODEL_API_KEY>`.
   If the registry previously had 67 entries and all six activate, expect 73
   entries and 61 enabled distinct leagues (provided no other changes happened).
   Optional `POST /models/<slug>/reload` can test model loading after deployment.
6. Update/sync the league catalogue in **Laravel separately**, unless Laravel
   already fetches the registry dynamically. FastAPI activation does not update
   Laravel's local database or create visible public tickets by itself.

## Safety rules

- Deployed source is an **additive merge**. It does not delete existing registry
  entries or disable existing models merely because those entries are absent
  from the Git update file.
- Existing model folders are **never replaced automatically** by default. A
  deliberate retraining rollout requires `PRIX_GIT_SYNC_REPLACE_EXISTING=1` on
  Render, which enables backed-up replacements. Test first and preserve backups.
- Source model folders must have `model_config.json` + `model_metadata_v064.json`,
  complete referenced `.pkl`/feature files and matching `sklearn_training_version`.
- `enabled:true` in the registry enables model lookup. `review_only` market rules
  remain in force, so public Free/Premium/Elite tickets are *not* auto-approved.
- If syncing is broken, revert the Git commit; emergency switch:
  `PRIX_GIT_MODEL_SYNC_DISABLED=1` (skips sync; existing disk remains).
- Watch disk capacity; replacement backups are kept under
  `/var/data/prix-models/.prix_git_sync_backups/` for administrator review.
- Large binaries can inflate Git repositories. GitHub blocks ordinary Git files
  over 100 MB; Git LFS or external object storage may be preferable for future
  very large batches. Make sure Render receives real files, not Git LFS pointers.
- The existing one-off `/admin/models/replace-seven-1-6-1` endpoint remains
  release-specific and is **not** used by this automation.

## Initial proof and rollback

No production deploy has been done by this patch package. Test in staging or
against a copy of the persistent disk. The sync takes a file lock, stages all
files, checks the combined registry before applying, retains backups when
replacing existing folders, and restores the prior state on a late error.
For a bad Git release, revert the commit and deploy the previous revision.
**Additions are intentionally persistent**: removing a league from the Git delta
will NOT delete that league or model from the live disk. Disable that registry
entry explicitly (`enabled: false`) if it should stop serving, or perform a
backed-up manual rollback. If an existing folder was deliberately replaced,
inspect `.prix_git_sync_backups` for the saved previous folder before recovery.
Never automatically delete historical/production model folders from Git sync.
Commit only trusted trained model files because Python joblib/pickle model
artifacts can execute code when deserialized by the model server.
If your repo uses `.gitignore` patterns that exclude `models` or `*.pkl`, make
sure the new `deploy_models/models/` files are actually staged by `git add`.
