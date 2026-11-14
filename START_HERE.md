# Start here: finish GitHub → Render model deployment

**Your six trained model folders are NOT in this ZIP.** Add them from your Colab results before pushing. The supplied `deploy_models/leagues.json` contains the six new England leagues. Your 67-entry persistent registry must already exist on Render.

1. Merge the `app/`, `scripts/`, `.github/`, `.gitattributes` and `deploy_models/leagues.json` files into your FastAPI repository. Merge suggested ignore rules into your existing `.gitignore` (do not overwrite it blindly).
2. In PowerShell, run `git lfs install`. Ensure `.pkl` files in `deploy_models/models` are not ignored by Git. Check that `.gitattributes` is staged before the model files.
3. Extract all six newly trained (sklearn 1.6.1) model folders under `deploy_models/models/<slug>/`.
4. Run:

   ```powershell
   python scripts/prepare_github_models.py --write
   python scripts/prepare_github_models.py --check
   ```

5. If the two old failed Git commits are still ahead of GitHub, make a backup branch and use `git reset --soft origin/main` to rebuild them as a clean commit. Instructions are in `README_GITHUB_RENDER_FINAL.md`. Do NOT use `git reset --hard`.
6. Run:

   ```powershell
   git add .gitattributes .github app scripts deploy_models
   git lfs ls-files
   git diff --cached --stat
   git commit -m "Enable GitHub Release model deployment for six England leagues"
   git push origin main
   ```

7. Wait for GitHub Actions **Validate and publish Prix models** to complete. Confirm GitHub Releases has `prix-models-latest` with asset `prix-models.zip`.
8. Set Render to **Auto Deploy → After CI Checks Pass**; enable `MODEL_ROOT=/var/data/prix-models`, `PRIX_GITHUB_MODEL_REPO=OWNER/REPO`, `PRIX_EXPECTED_SKLEARN_VERSION=1.6.1`, `PRIX_GIT_SYNC_MIN_BASE_ENTRIES=67`, `PRIX_GIT_SYNC_REPLACE_EXISTING=0`. Add `PRIX_GITHUB_MODEL_TOKEN` (fine-grained GitHub repo Contents read) if the repository is private.
9. Render's app startup will download and verify the GitHub Release model files, merge the new six leagues, and load the updated registry. In Postman call `GET /registry/git-sync-status`, `GET /registry/status` and `GET /registry/diagnostics` with `X-API-Key`. Expected **73 registry entries, 61 enabled distinct, 12 aliases, zero missing folders** if no other changes were made.
10. Laravel's admin database still requires its league mappings to be synchronized. The new models will remain `review_only` until approved separately.

**Status:** Code validated locally with synthetic artifacts and a real metadata check of a previously retrained sklearn 1.6.1 league; live GitHub/Render execution and six-league model deserialization are not yet verified.
