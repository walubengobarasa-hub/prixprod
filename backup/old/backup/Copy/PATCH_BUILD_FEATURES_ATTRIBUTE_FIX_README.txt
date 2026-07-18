Patch: build-features feature_columns attribute fix

Fixes:
- /build-features/{league_slug} no longer fails with:
  'LoadedLeagueModel' object has no attribute 'feature_columns'
- LoadedLeagueModel now exposes backward-compatible aliases:
  feature_columns -> raw_feature_columns
  fitted_feature_columns -> model_feature_columns
- /models and /models/{league_slug}/reload now report raw and fitted feature counts.
- Added/kept live FootyStats endpoints:
  POST /sync/league/{league_slug}
  POST /sync/completed/{league_slug}
  POST /sync/table/{league_slug}
  GET  /fixtures/{league_slug}
  GET  /fixtures/{league_slug}/{date}
  GET  /completed/{league_slug}
  POST /build-features/{league_slug}
  POST /predict/league/{league_slug}

Note:
- /build-features currently produces a minimal feature bridge from live FootyStats fixture fields.
- Full v0.4 rolling feature parity still needs to be ported from the notebook before live model-grade predictions.
