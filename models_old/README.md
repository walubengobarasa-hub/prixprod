# Model folders

Copy the production registry to `models/leagues.json` and place every canonical league bundle under `models/{league_slug}/`.

Each enabled league must follow the v0.6.4 structure demonstrated by the Latvia bundle and contain all files referenced by its `model_config.json`. Model files are intentionally not included in this patch archive.

The active-league test discovers canonical enabled leagues from `models/leagues.json`. It requires at least 29 canonical leagues and validates every enabled folder automatically.
