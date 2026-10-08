# PrixPredictor Model Training Control Plane

## Deploy order

1. Deploy the FastAPI bundle first.
2. On Render, use persistent storage for runtime model releases:
   - `MODEL_ROOT=/var/data/prix-models`
   - `MODEL_RELEASE_ROOT=/var/data/prix-model-releases`
3. Deploy the Laravel bundle.
4. Run `php artisan migrate` (preferred). A phpMyAdmin SQL fallback is in `setup/model-training/001_model_training_control_plane.sql`.
5. Open `/admin/model-training/competitions`.
6. Click **Import API Registry** once to copy the current FastAPI competition registry into Laravel.
7. Click **Sync FootyStats IDs** to refresh current season IDs.
8. Review active/training flags and click **Push Registry to API**.

## Non-technical training workflow

1. Add or edit competitions in Model Training > Competition & Model Manager.
2. Sync FootyStats IDs.
3. Select competitions and click **Generate & Download Colab Package**.
4. In Colab, upload/extract the ZIP and open `PrixPredictor_Train_Models.ipynb` (or a generated single-competition notebook).
5. Choose Runtime > Run all and allow Google Drive access.
6. Download the generated `PrixPredictor_Trained_Models_*.zip`.
7. Upload it in **Upload trained models**.
8. The server validates model family, model config and feature contract metadata before staging.
9. Click **Deploy**. Laravel sends the validated release and generated registry to FastAPI.
10. Use **Rollback here** if a prior release must be restored.

## Competition families

- `league_v064`: domestic league training using the established v0.6.4 leakage-safe training core.
- `continental_cup_v1`: continental cup family. Selected continental cup datasets are pooled to improve sample size but remain labelled and deployed as cup artifacts.
- `domestic_cup_v1`: domestic cup family trained separately per competition.

Cup artifacts are never accepted as league artifacts. The registry stores competition format and team/league-strength hooks for future feature enrichment.
