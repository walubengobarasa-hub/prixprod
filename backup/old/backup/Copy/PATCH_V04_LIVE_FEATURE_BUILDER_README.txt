PrixPredictor FastAPI v0.3 Live FootyStats Feature Builder Patch

What changed
------------
- Replaced the minimal live feature bridge with a v0.4-compatible rolling feature builder.
- /build-features/{league_slug} now builds 517 model feature columns from:
  - FootyStats completed matches before each fixture
  - Last 3 / 5 / 10 rolling team form
  - Home-only and away-only splits
  - Combined and difference features
  - Standard deviation features
  - Goal-floor and Under 1.5 risk trend features
  - FootyStats odds-derived features
- /predict/league/{league_slug} now uses the same live feature builder before running the existing model engine.
- The test API key may still return fixture_count = 0 because it returns a completed historical season only. That is expected.

How to test
-----------
1. Restart API:
   uvicorn app.main:app --reload

2. Run:
   python scripts/footystats_live_smoke_test.py

Expected with FootyStats test key:
- /sync/league/epl -> 200
- /completed/epl -> 200
- /build-features/epl -> 200 with feature_count 517 and feature_row_count 0 if no fixtures
- /predict/league/epl -> 200 with warning if no fixtures

Expected with live/current season key:
- fixture_count > 0
- feature_row_count should equal fixture_count
- /predict/league/epl returns candidates/tickets based on live fixture features
