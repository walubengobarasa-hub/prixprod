PrixPredictor FastAPI FootyStats live sync patch

Added/updated endpoints:

POST /sync/league/{league_slug}
- Pulls FootyStats league-matches.
- Normalizes completed matches and upcoming fixtures.
- Caches raw, normalized, completed, and fixture data.

POST /sync/completed/{league_slug}
- Refreshes completed matches only.

POST /sync/table/{league_slug}
- Pulls league table/stat snapshots.
- Supports max_time for point-in-time snapshots.

GET /fixtures/{league_slug}
GET /fixtures/{league_slug}/{date}
- Returns cached upcoming fixtures.

GET /completed/{league_slug}
- Returns cached completed matches.

POST /build-features/{league_slug}
- Builds a minimal live feature payload from cached/synced fixtures.
- This is a readiness bridge only. Full notebook v0.4 rolling-feature parity still needs to be ported before relying on live model-grade inputs.

Important:
- Set FOOTYSTATS_API_KEY in .env.
- Set models/leagues.json footystats_league_id for EPL.
- The existing /predict/features model-parity endpoint remains unchanged.
