from __future__ import annotations

import os
from pathlib import Path

import pytest

EXPECTED_ACTIVE_MARKETS = {"double_chance", "over_1_5", "match_outcome"}
REVIEW_ONLY_MARKETS = {"btts", "over_2_5"}


def test_registry_has_no_structural_errors():
    from app.league_registry import league_registry
    if not league_registry.list_leagues():
        pytest.skip("models/leagues.json is not present in this app-only patch.")
    assert league_registry.validate() == []


def test_every_enabled_model_loads_and_has_features():
    from app.league_registry import league_registry
    from app.model_registry import model_registry
    if not league_registry.enabled_slugs():
        pytest.skip("No league model folders are mounted.")
    results = model_registry.validate_all()
    failures = [row for row in results if not row.get("ok")]
    assert failures == []
    assert all(int(row.get("feature_count") or 0) > 0 for row in results)


def test_review_only_markets_cannot_publish():
    from app.predictor import _market_status
    config = {"market_rules": {market: {"status": "active"} for market in REVIEW_ONLY_MARKETS}}
    assert all(_market_status(config, market) == "review_only" for market in REVIEW_ONLY_MARKETS)


def test_match_outcome_is_strict_active_candidate():
    from app.predictor import _market_status
    assert _market_status({"market_rules": {"match_outcome": {"status": "review_only"}}}, "match_outcome") == "active"


def test_api_key_setting_uses_prix_name(monkeypatch):
    monkeypatch.setenv("PRIX_MODEL_API_KEY", "test-prix-key")
    from app.config import Settings
    assert Settings(_env_file=None).prix_model_api_key == "test-prix-key"


def test_fixture_date_uses_platform_timezone():
    from datetime import datetime, timezone
    from app.data_adapter import normalize_footystats_match

    timestamp = int(datetime(2026, 7, 17, 22, 30, tzinfo=timezone.utc).timestamp())
    normalized = normalize_footystats_match({
        "id": 1,
        "date_unix": timestamp,
        "home_name": "Home",
        "away_name": "Away",
    })
    assert normalized["kickoff_time"].startswith("2026-07-17T22:30:00")
    assert normalized["match_date"] == "2026-07-18"


def test_goal_minute_parser_handles_stoppage_time_and_ignores_non_goal_events():
    from app.feature_builder import _goal_minutes

    minutes = _goal_minutes({
        "goal_timings": "12,45+2",
        "events": [
            {"type": "yellow_card", "minute": 30},
            {"type": "goal", "minute": "90+4"},
        ],
    })
    assert minutes == [12.0, 47.0, 94.0]


def test_incomplete_status_is_not_completed():
    from app.data_adapter import is_completed_status

    assert is_completed_status("complete") is True
    assert is_completed_status("completed") is True
    assert is_completed_status("FT") is True
    assert is_completed_status("incomplete") is False
    assert is_completed_status("scheduled") is False


def test_future_incomplete_fixture_remains_fixture(monkeypatch):
    from datetime import datetime, timezone
    from app.main import _classify_matches

    kickoff = int(datetime(2099, 7, 18, 12, 0, tzinfo=timezone.utc).timestamp())
    raw = [{
        "id": 99,
        "date_unix": kickoff,
        "home_name": "Home",
        "away_name": "Away",
        "status": "incomplete",
    }]
    completed, fixtures = _classify_matches(raw, "2099-07-18", "2099-07-18")
    assert completed == []
    assert fixtures == raw


def test_enabled_registry_slugs_exclude_aliases():
    from app.league_registry import league_registry
    if not league_registry.list_leagues():
        pytest.skip("models/leagues.json is not present.")
    enabled = set(league_registry.enabled_slugs())
    aliases = {slug for slug, meta in league_registry.list_leagues().items() if (meta or {}).get("alias_for")}
    assert enabled.isdisjoint(aliases)


def test_prediction_window_limit_setting_is_at_least_three_days():
    from app.config import settings
    assert int(settings.max_prediction_window_days) >= 3


def test_prediction_window_rejects_more_than_configured_limit():
    from datetime import date, timedelta
    from fastapi import HTTPException
    from app.config import settings
    from app.main import predict_eligible
    from app.schemas import EligiblePredictionRequest

    start = date(2026, 7, 18)
    end = start + timedelta(days=int(settings.max_prediction_window_days) + 1)
    with pytest.raises(HTTPException) as exc:
        predict_eligible(EligiblePredictionRequest(
            leagues=[],
            date_from=start.isoformat(),
            date_to=end.isoformat(),
        ))
    assert exc.value.status_code == 422
