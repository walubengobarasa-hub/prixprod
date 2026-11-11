# Prix Predictor — Missing model folders, low-memory upload

Use this patch ONLY with the latest deployed FastAPI build from the 2026-11-02 UEFA/registry/diagnostics patch. It adds one authenticated endpoint and makes no changes to existing model folders, leagues.json, model inference, payment, or Laravel.

## Contents
- `app/main.py`: latest previously released FastAPI main plus raw ZIP upload route.
- `app/model_folder_installer.py`: disk-streaming, validate-before-install extraction for ten explicit missing folders.
- Separate model artifact ZIP: `prix_missing_10_models_20261103.zip` (download separately).

## Deployment
1. Back up your FastAPI source. Merge or replace the two `app/` files in your Render repository, then redeploy the **prixmodel** service. This installation patch itself contains no trained models.
2. In Postman create `POST https://prixmodel.onrender.com/admin/models/install-missing`.
3. Headers: `X-API-Key: <existing private key>` and `Content-Type: application/zip`.
4. Body: **binary** -> Select File -> `prix_missing_10_models_20261103.zip`. Do not use raw JSON/form-data; do not base64 encode.
5. Click Send. Expect HTTP 200 JSON with `installed_count: 10` and the folder names. The installer refuses existing folders and any unsupported folders/files and will not overwrite original models. Archive size ~16.1 MiB.
6. Then send the previously supplied JSON request to `POST /admin/registry/apply` with raw JSON; it should return `ok: true` and `/health` should show `registered_leagues: 48`.
7. Check lightweight authenticated `GET /registry/status`, then run Laravel league diagnostics. **Do not run `/models/validate` on all 48 models at once** on low-memory Render.

## Safety
The request is authenticated by the existing `require_api_key` dependency; no API key in code. Maximum uploaded size 60 MiB and expanded content 240 MiB; rejects unsafe ZIP paths and symlinks. Installation writes to a staging directory under active `MODEL_ROOT` and only then moves brand-new folders into place. It won't overwrite 38 existing model folders or your registry. Trained `.pkl` files are not opened during upload.

## Limits
Upload is a one-time maintenance operation. Avoid concurrent requests to this endpoint or any prediction-generating jobs during maintenance. If some model folders already exist, do not run this 10-folder bundle unchanged; report the response and create a smaller bundle for only the truly missing ones. Memory spikes remain possible during model inference; this patch avoids the heavy full-registry model validation performed by `/admin/releases/deploy`.
