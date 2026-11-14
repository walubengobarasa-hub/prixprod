# Prix Predictor — Local → GitHub → Render automatic model deployment

## What was changed in your supplied FastAPI app

- `app/main.py` invokes `sync_render_models()` **before** `league_registry` and `model_registry` import. After a successful deployment, the new registry is loaded without manually calling Postman `/registry/reload`.
- `app/github_model_release.py` fetches the GitHub Release asset at Render *runtime*, checks the asset digest when available and verifies every extracted file against the Git-committed `model_manifest.json`. Safe ZIP extraction rejects unknown paths, unsafe paths, symlinks and missing/mismatched files. Subsequent restarts reuse already-verified disk models after checking file checksums.
- `app/git_model_sync.py` retains the prior safe merge, backup and rollback logic and now accepts an externally validated model-folder staging path. It never deletes existing 67+ registry entries or unrelated model folders.
- `.github/workflows/publish-prix-models.yml` downloads models from Git LFS when model files change, verifies the manifest, and publishes a `prix-models.zip` asset to the GitHub Release tagged `prix-models-latest`. Code-only pushes reuse the existing release.
- `.gitattributes` stores `*.pkl` and `*.joblib` as Git LFS objects to avoid another giant ordinary Git pack.
- `deploy_models/leagues.json` has the six England additions from the earlier generated registry delta. **Trained model folders were NOT included in your upload and are NOT in this package.**

## One-time setup

1. **Back up your local repo and existing Render persistent disk** (`/var/data/prix-models`, including `leagues.json`). Keep a local copy of your trained model ZIP.
2. Merge this package **into your current repo**. Do not delete existing `.env`, `requirements.txt`, `render.yaml`, source files or config. The ZIP contains the modified app and scripts, `.github` workflow, `.gitattributes`, and a suggested `.gitignore.suggested` (merge the rules into your existing `.gitignore`; do not blindly replace it). Do not include `main.py.before-git-sync`, `__pycache__`, or historical `backup/` in new commits.
3. Ensure `requests`, `fastapi`, `pydantic-settings` are in the existing requirements. **Keep** `scikit-learn==1.6.1` pinned; do not upgrade it to match an incompatible model. Leave your existing dependency versions alone otherwise.
4. Install **Git LFS** on your Windows PC. Run `git lfs install` in PowerShell. Confirm `git lfs version`. **Ensure your existing `.gitignore` does NOT ignore `*.pkl`, `*.joblib`, or `deploy_models/models/`;** they need to be tracked through LFS. Do not track the old `models_old/` folder.
5. Copy *only* the six newly trained model folders into `deploy_models/models/<model_folder>/` (one folder for each of the six `deploy_models/leagues.json` records). No ZIP uploads to Git; keep model files unzipped. Run `python scripts/prepare_github_models.py --write` and `python scripts/prepare_github_models.py --check`. The script refuses Git LFS pointer files and sklearn versions other than 1.6.1.
6. Check `git check-attr filter -- deploy_models/models/england-championship/<example-model>.pkl` returns `filter: lfs`. Run `git lfs ls-files` after staging and review which files will be uploaded.
7. **Your earlier HTTP 408 fix:** you previously had two local commits not yet pushed. Before staging the new deployment, use:
   ```powershell
   git fetch origin
   git branch backup/pre-model-release-integration
   git reset --soft origin/main
   ```
   This preserves final staged changes and your working files. Then review `git status`, unstage unneeded model/old backup files, and commit the new final tree. Never use `git reset --hard` or force-push. Adding `.gitattributes` does not convert old unpushed model objects automatically; after the soft reset, `git add --renormalize deploy_models/models` can reapply Git LFS attributes. If `git rev-list --objects origin/main..HEAD` still points to huge objects, do not repeat the push—inspect what is staged first.
8. `git add .gitattributes .github app scripts deploy_models` (also stage your existing `.gitignore` only if you modified it) (merge with your real repo and check `git status`). Run `git diff --cached --stat`. Commit and run `git push origin main`. Expect Git LFS uploads for actual model bytes and a much smaller regular Git pack. Git LFS uses storage/bandwidth quotas that depend on your GitHub plan.
9. GitHub → repository → **Actions** → confirm **Validate and publish Prix models** succeeded. In **Releases**, the tag `prix-models-latest` must have the `prix-models.zip` asset. Repository **Actions permissions** must allow workflows to write repository contents (or the workflow's `contents: write` permission may be blocked by organization policy).
10. Render → FastAPI service → **Auto-Deploy: After CI Checks Pass**, so Render doesn't pull the new commit before GitHub Actions has published the release. Verify the linked branch is `main`. Render will redeploy when the GitHub check passes. If this mode is unavailable, use a GitHub Actions-triggered Render deploy hook after the release upload instead; never use simultaneous uncontrolled deploys for a model batch.
11. Render environment settings:
    ```text
    MODEL_ROOT=/var/data/prix-models
    PRIX_EXPECTED_SKLEARN_VERSION=1.6.1
    PRIX_GITHUB_MODEL_REPO=YOUR_GITHUB_USERNAME/YOUR_FASTAPI_REPO
    PRIX_GITHUB_MODEL_RELEASE_TAG=prix-models-latest
    PRIX_GIT_SYNC_MIN_BASE_ENTRIES=67
    PRIX_GIT_SYNC_REPLACE_EXISTING=0
    ```
    For a **private** GitHub repository, also set `PRIX_GITHUB_MODEL_TOKEN` to a fine-grained token with repository **Contents: read** permission. Keep it in Render Environment, never in Git. A public GitHub Release is public to anyone if the repository is public.
12. Make sure Render starts `app.main:app` (for example `uvicorn app.main:app --host 0.0.0.0 --port $PORT`), and that the persistent disk mount is `/var/data`. The model files are copied during *application startup*, not build or pre-deploy (Render does not attach disks during those steps).

## Verify after each GitHub → Render deployment

In Postman with the existing `X-API-Key`:

| Request | Expected |
| --- | --- |
| `GET /registry/git-sync-status` | `ok: true`, `source: github_release`; `installed` lists six on first install, `unchanged` on repeats |
| `GET /registry/status` | 73 total entries, 61 enabled distinct, 12 aliases, `missing_model_folders: []`, `registry_errors: []` |
| `GET /registry/diagnostics` | Newly installed folders have compatible model metadata |
| `POST /models/england-championship/reload` | Model loads if dependencies/feature contract match |

The 73-entry baseline assumes your disk still had the original 67 entries. Only the six new leagues are merged. The old 48-league model folders and seven retrained leagues are preserved. The new markets retain `review_only` settings until separately approved. **FastAPI registry activation does not create matching entries in the Laravel admin database**; synchronize Laravel's six league records/season IDs before running ticket generation.

## Troubleshooting

- **Git push HTTP 408 / 685 MB:** Old unpushed Git objects still in history, not a `.gitignore` problem. Rebuild the unpublished commits as described above; verify `git lfs ls-files` before push.
- **GitHub Action fails because models missing:** This ZIP contains no trained model files. Add the real six model folders and regenerate `model_manifest.json`.
- **GitHub Action reports LFS pointers:** Check out actual LFS objects with `git lfs pull`, then rerun manifest validation.
- **Render fails with 404 GitHub API:** Check repo name, Release tag, asset, and private-repo token permissions.
- **Render fails with manifest mismatch:** Release and current commit have different model files. Allow the matching GitHub Action run to finish, or restore the release from the corresponding Git commit; do not bypass integrity validation.
- **Render version mismatch:** Train using sklearn 1.6.1; don't edit metadata manually.
- **Existing models differ:** Replacements are blocked by default. For deliberate retrains, back up the seven or six folders and enable `PRIX_GIT_SYNC_REPLACE_EXISTING=1` only for that controlled rollout, then revert to `0`.
- **Registry still 67:** Review startup logs and `/registry/git-sync-status`; check missing six folders, invalid manifest, or GitHub Release download failure.

**Not tested on production:** The package passes local synthetic tests, but no live GitHub Action, Render download, sklearn 1.6.1 deserialization, or paid-production prediction test can be performed without your GitHub repository, Render runtime and the six trained model binaries.

**Disk space:** Allow enough free persistent-disk capacity to download the Release archive and stage another temporary copy of each model during the atomic install. Do not reduce the disk size or remove existing folders to make space. GitHub LFS transfer/storage may incur plan charges.
