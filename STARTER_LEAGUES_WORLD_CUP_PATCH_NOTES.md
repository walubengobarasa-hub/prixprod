# PrixPredictor FastAPI Patch

Patched on the uploaded `FastApi(3).zip` build.

## Added leagues

- canada
- chile
- china
- ecuador
- estonia
- finland
- iceland
- korea
- latvia
- lithuania
- allsvenskan
- sweden alias -> allsvenskan
- uruguay
- world-cup
- worldcup alias -> world-cup
- epl remains registered

## Engine changes

- Starter league model folders integrated from v0.4.2/v0.4.2.2 outputs.
- World Cup v0.5 remains supported.
- Supports over_1_5, over_2_5, double_chance, match_outcome, btts candidates.
- Supports under15_risk, under25_risk, draw_risk, favorite_win and favorite_avoid_defeat as support/risk models where artifacts are available.
- Adds item-level league metadata for Laravel.
- Keeps cross-league packaging support.
- Keeps per-league market gates from model configs.
- Includes sklearn compatibility patch for Colab-trained artifacts.
- Finland is registered but disabled by default because latest review showed weak production accuracy.

## FootyStats

Starter leagues have model artifacts loaded, but most `footystats_league_id` / `footystats_season_id` values are currently null. Add real FootyStats IDs before using live sync endpoints for those leagues.
