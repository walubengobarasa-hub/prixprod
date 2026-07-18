# PrixPredictor Model API v0.1

FastAPI service for football analytics forecasting and candidate packaging. Laravel remains responsible for users, payments, admin, frontend display, publishing, and access control.

## First integration path

Use `/predict/features` first. It expects already-engineered feature rows matching the `feature_columns.json` exported from Colab. This lets us prove model serving and Laravel integration before relying on live feature parity.

## Required EPL artifacts

Drop these in `models/epl/`:

```text
model_config.json
feature_columns.json
epl_over15_base_model.pkl
epl_under15_risk_model.pkl
epl_outcome_calibrated_model.pkl
epl_btts_base_model.pkl
epl_favorite_win_model.pkl
epl_favorite_avoid_defeat_model.pkl
```

If filenames differ, edit `models/epl/model_config.json`.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Docs: `http://127.0.0.1:8000/docs`

## Main endpoints

```text
GET  /health
GET  /models
POST /predict/features
POST /sync/league/{league_slug}
POST /predict/league/{league_slug}
```

Use header `X-API-Key` for protected endpoints once `PREDICTOR_API_KEY` is changed from `change-me`.


## v0.6.4 explainable model support

This build supports the new v0.6.4 explainable artifacts exported by the Colab runner.

Active candidate markets are:

- `double_chance`
- `over_1_5`
- `match_outcome`

`btts` and `over_2_5` remain review-only unless a league config explicitly opens them. Match Outcome uses stricter candidature gates: confidence, draw-risk, agreement, and favorite-support checks.

Prediction responses now include:

- `explanation`
- `reason_codes`
- `top_factors`
- `goal_timing_estimate`
- `winner_decision_estimate`

Timing fields are estimates based on historical profiles, not guarantees.

### Install future trained leagues

After running the v0.6.4 Colab runner and downloading/copying output folders, install them into the API with:

```bash
python scripts/install_v064_artifacts.py /path/to/model_outputs/v064
```

Then restart FastAPI or call:

```bash
curl -X POST "$API/models/{league_slug}/reload" -H "X-API-Key: $PRIX_MODEL_API_KEY"
```

### Local smoke test

```bash
python scripts/v064_explainability_smoke_test.py allsvenskan
python scripts/v064_explainability_smoke_test.py finland
```
