# PrixPredictor FastAPI Patch

## Included

- Root service-status endpoint at `/`.
- Existing `/health`, `/models/validate`, and `/predict/eligible` endpoints remain unchanged.
- Render environment example with production settings.

## Render environment

Set the values in `RENDER_ENV.example` through the Render environment settings. Keep the production model folders and `models/leagues.json` already deployed on the service.
