from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _available_model_slug():
    from app.league_registry import league_registry
    slugs = league_registry.enabled_slugs()
    return slugs[0] if slugs else None


def test_live_builder_produces_non_zero_model_features():
    slug = _available_model_slug()
    if not slug:
        pytest.skip("No model folders are mounted.")
    from app.feature_builder import build_live_feature_rows_from_footystats
    from app.model_registry import model_registry

    loaded = model_registry.get(slug)
    teams = ["Home FC", "Away FC", "Third FC", "Fourth FC"]
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    completed = []
    for index in range(36):
        completed.append({
            "id": index + 1,
            "status": "complete",
            "date_unix": int((base + timedelta(days=index * 3)).timestamp()),
            "home_name": teams[index % 4],
            "away_name": teams[(index + 1) % 4],
            "homeGoalCount": index % 4,
            "awayGoalCount": (index + 1) % 3,
            "team_a_xg": 1.4,
            "team_b_xg": 1.1,
            "team_a_shots": 12,
            "team_b_shots": 9,
            "team_a_shotsOnTarget": 5,
            "team_b_shotsOnTarget": 4,
            "team_a_corners": 6,
            "team_b_corners": 4,
            "team_a_cards": 2,
            "team_b_cards": 2,
        })
    fixture = {
        "id": 9999,
        "status": "incomplete",
        "date_unix": int((base + timedelta(days=140)).timestamp()),
        "home_name": "Home FC",
        "away_name": "Away FC",
        "odds_ft_1": 1.8,
        "odds_ft_x": 3.5,
        "odds_ft_2": 4.2,
        "odds_ft_over15": 1.25,
        "odds_ft_over25": 1.85,
        "home_ppg": 2.0,
        "away_ppg": 1.5,
        "pre_match_home_xg": 1.7,
        "pre_match_away_xg": 1.2,
    }
    rows = build_live_feature_rows_from_footystats(slug, [fixture], completed, loaded.raw_feature_columns)
    assert len(rows) == 1
    quality = rows[0]["feature_meta"]
    assert quality["expected_features"] == len(loaded.raw_feature_columns)
    assert quality["non_zero_features"] > 0
    assert quality["coverage_ratio"] >= 0.15
    assert quality["leakage_safe"] is True
