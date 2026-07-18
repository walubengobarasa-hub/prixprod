from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

from app.config import settings
from app.data_adapter import normalize_footystats_match


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        result = float(value)
        if pd.isna(result):
            return default
        return result
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _first(data: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None and data[key] != "":
            return data[key]
    return default


def _parse_date(value: Any) -> pd.Timestamp:
    if value is None or value == "":
        return pd.NaT
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return pd.to_datetime(int(float(value)), unit="s", utc=True).tz_convert(None)
        return pd.to_datetime(value, utc=True).tz_convert(None)
    except Exception:
        return pd.NaT


def _avg(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(pd.Series(values, dtype="float64").std(ddof=0))


def _raw_match(match: dict[str, Any]) -> dict[str, Any]:
    return match.get("raw", match)


def _match_datetime(raw: dict[str, Any]) -> pd.Timestamp:
    return _parse_date(
        _first(raw, ["date_unix", "timestamp", "kickoff_unix", "date", "match_date", "kickoff", "kickoff_time"], None)
    )


def _team_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _result_points(goals_for: int, goals_against: int) -> tuple[int, int, int, int]:
    if goals_for > goals_against:
        return 3, 1, 0, 0
    if goals_for == goals_against:
        return 1, 0, 1, 0
    return 0, 0, 0, 1


def _extract_minutes(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: list[float] = []
        for item in value:
            if isinstance(item, dict):
                minute = _first(item, ["minute", "time", "min"], None)
                if minute is not None:
                    out.append(_safe_float(minute))
            else:
                out.extend(_extract_minutes(item))
        return [x for x in out if x >= 0]
    if isinstance(value, dict):
        return _extract_minutes(list(value.values()))
    minutes: list[float] = []
    for base, added in re.findall(r"(\d+(?:\.\d+)?)(?:\+(\d+(?:\.\d+)?))?", str(value)):
        minute = _safe_float(base) + (_safe_float(added) if added else 0.0)
        minutes.append(minute)
    return minutes


def _event_goal_minutes(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: list[float] = []
    for event in value:
        if not isinstance(event, dict):
            continue
        label = str(_first(event, ["type", "event_type", "event", "name", "detail"], "")).lower()
        if label and "goal" not in label:
            continue
        minute = _first(event, ["minute", "time", "min"], None)
        if minute is not None:
            parsed = _extract_minutes(minute)
            if parsed:
                out.append(parsed[0])
    return out


def _goal_minutes(raw: dict[str, Any]) -> list[float]:
    minutes: list[float] = []
    for key in [
        "goal_timings",
        "goals",
        "goal_events",
        "homeGoalTimings",
        "awayGoalTimings",
        "team_a_goal_timings",
        "team_b_goal_timings",
    ]:
        if key in raw:
            minutes.extend(_extract_minutes(raw.get(key)))
    # Generic event lists may include cards and substitutions, so only retain
    # entries explicitly identified as goals.
    if "events" in raw:
        minutes.extend(_event_goal_minutes(raw.get("events")))
    return sorted([x for x in minutes if 0 <= x <= 130])


def _team_metric(raw: dict[str, Any], side: str, metric: str, default: float = 0.0) -> float:
    aliases: dict[str, dict[str, list[str]]] = {
        "xg": {
            "home": ["team_a_xg", "home_xg", "home_xG", "home_expected_goals", "xg_home"],
            "away": ["team_b_xg", "away_xg", "away_xG", "away_expected_goals", "xg_away"],
        },
        "shots": {
            "home": ["team_a_shots", "home_shots", "HS"],
            "away": ["team_b_shots", "away_shots", "AS"],
        },
        "sot": {
            "home": ["team_a_shotsOnTarget", "team_a_shots_on_target", "home_shots_on_target", "HST"],
            "away": ["team_b_shotsOnTarget", "team_b_shots_on_target", "away_shots_on_target", "AST"],
        },
        "corners": {
            "home": ["team_a_corners", "home_corners", "HC"],
            "away": ["team_b_corners", "away_corners", "AC"],
        },
        "yellow": {
            "home": ["team_a_yellow_cards", "home_yellow_cards", "HY"],
            "away": ["team_b_yellow_cards", "away_yellow_cards", "AY"],
        },
        "red": {
            "home": ["team_a_red_cards", "home_red_cards", "HR"],
            "away": ["team_b_red_cards", "away_red_cards", "AR"],
        },
    }
    return _safe_float(_first(raw, aliases.get(metric, {}).get(side, []), default), default)


def _completed_to_appearances(completed_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in completed_matches:
        raw = _raw_match(item)
        normalized = normalize_footystats_match(raw)
        match_dt = _match_datetime(raw)
        if pd.isna(match_dt):
            match_dt = _parse_date(normalized.get("kickoff_time") or normalized.get("match_date"))

        home = normalized.get("home_team") or ""
        away = normalized.get("away_team") or ""
        if not home or not away or pd.isna(match_dt):
            continue

        home_goals_raw = _first(raw, ["homeGoalCount", "home_goals", "FTHG"], None)
        away_goals_raw = _first(raw, ["awayGoalCount", "away_goals", "FTAG"], None)
        # Do not turn incomplete or malformed historical rows into artificial 0-0 draws.
        if home_goals_raw is None or away_goals_raw is None:
            continue
        home_goals = _safe_int(home_goals_raw)
        away_goals = _safe_int(away_goals_raw)
        total_goals = home_goals + away_goals
        half_home = _safe_int(_first(raw, ["ht_goals_team_a", "homeGoalsHalfTime", "HTHG"], 0))
        half_away = _safe_int(_first(raw, ["ht_goals_team_b", "awayGoalsHalfTime", "HTAG"], 0))
        first_half_goal = 1.0 if half_home + half_away > 0 else 0.0
        second_half_goal = 1.0 if total_goals - half_home - half_away > 0 else 0.0
        minutes = _goal_minutes(raw)
        first_goal_min = min(minutes) if minutes else 0.0
        last_goal_min = max(minutes) if minutes else 0.0

        home_points, home_win, home_draw, home_loss = _result_points(home_goals, away_goals)
        away_points, away_win, away_draw, away_loss = _result_points(away_goals, home_goals)

        home_xg = _team_metric(raw, "home", "xg")
        away_xg = _team_metric(raw, "away", "xg")
        home_shots = _team_metric(raw, "home", "shots")
        away_shots = _team_metric(raw, "away", "shots")
        home_sot = _team_metric(raw, "home", "sot")
        away_sot = _team_metric(raw, "away", "sot")
        home_corners = _team_metric(raw, "home", "corners")
        away_corners = _team_metric(raw, "away", "corners")
        home_cards_total = _first(raw, ["team_a_cards", "home_cards"], None)
        away_cards_total = _first(raw, ["team_b_cards", "away_cards"], None)
        home_cards = _safe_float(home_cards_total) if home_cards_total is not None else (_team_metric(raw, "home", "yellow") + _team_metric(raw, "home", "red"))
        away_cards = _safe_float(away_cards_total) if away_cards_total is not None else (_team_metric(raw, "away", "yellow") + _team_metric(raw, "away", "red"))

        common = {
            "date": match_dt,
            "match_external_id": str(normalized.get("match_external_id", "")),
            "over_1_5": 1.0 if total_goals >= 2 else 0.0,
            "over_2_5": 1.0 if total_goals >= 3 else 0.0,
            "btts": 1.0 if home_goals > 0 and away_goals > 0 else 0.0,
            "first_goal_min": first_goal_min,
            "last_goal_min": last_goal_min,
            "first_half_goal": first_half_goal,
            "second_half_goal": second_half_goal,
        }

        rows.append(
            {
                **common,
                "team": home,
                "team_key": _team_key(home),
                "opponent": away,
                "opponent_key": _team_key(away),
                "venue": "home",
                "goals_for": float(home_goals),
                "goals_against": float(away_goals),
                "points": float(home_points),
                "goal_diff": float(home_goals - away_goals),
                "win": float(home_win),
                "draw": float(home_draw),
                "loss": float(home_loss),
                "clean_sheet": 1.0 if away_goals == 0 else 0.0,
                "scored_2plus": 1.0 if home_goals >= 2 else 0.0,
                "conceded_2plus": 1.0 if away_goals >= 2 else 0.0,
                "shots_for": home_shots,
                "shots_against": away_shots,
                "sot_for": home_sot,
                "sot_against": away_sot,
                "corners_for": home_corners,
                "corners_against": away_corners,
                "cards_for": home_cards,
                "cards_against": away_cards,
                "xg_for": home_xg,
                "xg_against": away_xg,
            }
        )
        rows.append(
            {
                **common,
                "team": away,
                "team_key": _team_key(away),
                "opponent": home,
                "opponent_key": _team_key(home),
                "venue": "away",
                "goals_for": float(away_goals),
                "goals_against": float(home_goals),
                "points": float(away_points),
                "goal_diff": float(away_goals - home_goals),
                "win": float(away_win),
                "draw": float(away_draw),
                "loss": float(away_loss),
                "clean_sheet": 1.0 if home_goals == 0 else 0.0,
                "scored_2plus": 1.0 if away_goals >= 2 else 0.0,
                "conceded_2plus": 1.0 if home_goals >= 2 else 0.0,
                "shots_for": away_shots,
                "shots_against": home_shots,
                "sot_for": away_sot,
                "sot_against": home_sot,
                "corners_for": away_corners,
                "corners_against": home_corners,
                "cards_for": away_cards,
                "cards_against": home_cards,
                "xg_for": away_xg,
                "xg_against": home_xg,
            }
        )

    rows.sort(key=lambda row: (row["date"], row["match_external_id"], row["team"]))
    return rows


ROLLING_METRICS = [
    "btts",
    "cards_against",
    "cards_for",
    "clean_sheet",
    "conceded_2plus",
    "corners_against",
    "corners_for",
    "draw",
    "first_goal_min",
    "first_half_goal",
    "goal_diff",
    "goals_against",
    "goals_for",
    "last_goal_min",
    "loss",
    "over_1_5",
    "over_2_5",
    "points",
    "scored_2plus",
    "second_half_goal",
    "shots_against",
    "shots_for",
    "sot_against",
    "sot_for",
    "win",
    "xg_against",
    "xg_for",
]

PRIOR_METRICS = ["btts", "draw", "goals_against", "goals_for", "loss", "over_1_5", "points", "win"]


def _add_team_features(features: dict[str, float], side: str, history: list[dict[str, Any]]) -> None:
    prefix = f"{side}_team"
    for window in (3, 5, 10):
        selected = history[-window:]
        for metric in ROLLING_METRICS:
            features[f"{prefix}_last_{window}_{metric}"] = _avg([_safe_float(row.get(metric)) for row in selected])
    for metric in PRIOR_METRICS:
        values = [_safe_float(row.get(metric)) for row in history]
        features[f"{prefix}_prior_mean_{metric}"] = _avg(values)
        features[f"{prefix}_prior_std_{metric}"] = _std(values)


def _add_combined_features(features: dict[str, float]) -> None:
    for window in (3, 5, 10):
        for metric in ROLLING_METRICS:
            home = features.get(f"home_team_last_{window}_{metric}", 0.0)
            away = features.get(f"away_team_last_{window}_{metric}", 0.0)
            features[f"combined_team_last_{window}_{metric}"] = home + away
            features[f"diff_team_last_{window}_{metric}"] = home - away


def _implied_prob(odds: float) -> float:
    return 1.0 / odds if odds > 0 else 0.0


def _normalise_probs(values: list[float]) -> list[float]:
    total = sum(values)
    return [value / total for value in values] if total > 0 else [0.0 for _ in values]


def _odds(raw: dict[str, Any], keys: list[str]) -> float:
    return _safe_float(_first(raw, keys, 0.0))


def _add_odds_features(features: dict[str, float], raw: dict[str, Any]) -> None:
    home = _odds(raw, ["odds_ft_1", "odds_home", "AvgH", "BbAvH", "B365H"])
    draw = _odds(raw, ["odds_ft_x", "odds_draw", "AvgD", "BbAvD", "B365D"])
    away = _odds(raw, ["odds_ft_2", "odds_away", "AvgA", "BbAvA", "B365A"])
    over15 = _odds(raw, ["odds_ft_over15", "odds_over15", "odds_over_1_5", "over_1_5_odds"])
    over25 = _odds(raw, ["odds_ft_over25", "odds_over25", "Avg>2.5", "BbAv>2.5", "P>2.5"])
    over35 = _odds(raw, ["odds_ft_over35", "odds_over35", "odds_over_3_5"])
    over45 = _odds(raw, ["odds_ft_over45", "odds_over45", "odds_over_4_5"])
    btts_yes = _odds(raw, ["odds_btts_yes", "odds_ft_btts_yes", "btts_yes_odds"])
    btts_no = _odds(raw, ["odds_btts_no", "odds_ft_btts_no", "btts_no_odds"])

    exact = {
        "odds_ft_home_team_win": home,
        "odds_ft_draw": draw,
        "odds_ft_away_team_win": away,
        "odds_ft_over15": over15,
        "odds_ft_over25": over25,
        "odds_ft_over35": over35,
        "odds_ft_over45": over45,
        "odds_btts_yes": btts_yes,
        "odds_btts_no": btts_no,
        "implied_odds_ft_home_team_win": _implied_prob(home),
        "implied_odds_ft_draw": _implied_prob(draw),
        "implied_odds_ft_away_team_win": _implied_prob(away),
        "implied_odds_ft_over15": _implied_prob(over15),
        "implied_odds_ft_over25": _implied_prob(over25),
        "implied_odds_btts_yes": _implied_prob(btts_yes),
        "implied_odds_btts_no": _implied_prob(btts_no),
    }
    features.update(exact)

    one_x_two = _normalise_probs([
        exact["implied_odds_ft_home_team_win"],
        exact["implied_odds_ft_draw"],
        exact["implied_odds_ft_away_team_win"],
    ])
    features["odds_home_prob"] = one_x_two[0]
    features["odds_draw_prob"] = one_x_two[1]
    features["odds_away_prob"] = one_x_two[2]
    features["odds_favorite_prob"] = max(one_x_two) if one_x_two else 0.0
    features["odds_draw_risk_proxy"] = one_x_two[1]


def _pre_match(raw: dict[str, Any], keys: list[str]) -> float:
    return _safe_float(_first(raw, keys, 0.0))


def _add_pre_match_features(features: dict[str, float], raw: dict[str, Any]) -> int:
    aliases = {
        "average_cards_per_match_pre_match": ["average_cards_per_match_pre_match", "avg_cards_per_match_pre_match"],
        "average_corners_per_match_pre_match": ["average_corners_per_match_pre_match", "avg_corners_per_match_pre_match"],
        "average_goals_per_match_pre_match": ["average_goals_per_match_pre_match", "avg_goals_per_match_pre_match"],
        "btts_percentage_pre_match": ["btts_percentage_pre_match", "btts_potential", "btts_percentage"],
        "game_week": ["game_week", "gameweek", "round", "week"],
        "over_05_2HG_percentage_pre_match": ["over_05_2HG_percentage_pre_match", "over_05_2hg_percentage_pre_match"],
        "over_05_2hg_percentage_pre_match": ["over_05_2hg_percentage_pre_match", "over_05_2HG_percentage_pre_match"],
        "over_05_HT_FHG_percentage_pre_match": ["over_05_HT_FHG_percentage_pre_match", "over_05_ht_fhg_percentage_pre_match"],
        "over_05_ht_fhg_percentage_pre_match": ["over_05_ht_fhg_percentage_pre_match", "over_05_HT_FHG_percentage_pre_match"],
        "over_15_2HG_percentage_pre_match": ["over_15_2HG_percentage_pre_match", "over_15_2hg_percentage_pre_match"],
        "over_15_2hg_percentage_pre_match": ["over_15_2hg_percentage_pre_match", "over_15_2HG_percentage_pre_match"],
        "over_15_HT_FHG_percentage_pre_match": ["over_15_HT_FHG_percentage_pre_match", "over_15_ht_fhg_percentage_pre_match"],
        "over_15_ht_fhg_percentage_pre_match": ["over_15_ht_fhg_percentage_pre_match", "over_15_HT_FHG_percentage_pre_match"],
        "over_15_percentage_pre_match": ["over_15_percentage_pre_match", "over15_potential", "over_1_5_percentage"],
        "over_25_percentage_pre_match": ["over_25_percentage_pre_match", "over25_potential", "over_2_5_percentage"],
        "over_35_percentage_pre_match": ["over_35_percentage_pre_match", "over35_potential"],
        "over_45_percentage_pre_match": ["over_45_percentage_pre_match", "over45_potential"],
        "pre_match_ppg_home": ["pre_match_ppg_home", "home_ppg", "home_ppg_pre_match", "team_a_ppg"],
        "pre_match_ppg_away": ["pre_match_ppg_away", "away_ppg", "away_ppg_pre_match", "team_b_ppg"],
        "home_team_pre_match_xg": [
            "home_team_pre_match_xg", "team_a_xg_prematch", "home_xg_prematch",
            "pre_match_home_xg", "home_xg_pre_match", "team_a_pre_match_xg",
        ],
        "away_team_pre_match_xg": [
            "away_team_pre_match_xg", "team_b_xg_prematch", "away_xg_prematch",
            "pre_match_away_xg", "away_xg_pre_match", "team_b_pre_match_xg",
        ],
    }
    count = 0
    for target, keys in aliases.items():
        value = _pre_match(raw, keys)
        features[target] = value
        if value != 0:
            count += 1
    return count


def _add_derived_profiles(features: dict[str, float]) -> None:
    combined_goals = features.get("combined_team_last_5_goals_for", 0.0)
    combined_xg = features.get("combined_team_last_5_xg_for", 0.0)
    combined_sot = features.get("combined_team_last_5_sot_for", 0.0)
    over15 = features.get("combined_team_last_5_over_1_5", 0.0) / 2.0
    second_half = features.get("combined_team_last_5_second_half_goal", 0.0) / 2.0
    first_goal = features.get("combined_team_last_5_first_goal_min", 0.0) / 2.0

    pressure = (
        min(combined_goals / 5.0, 1.0) * 30
        + min(combined_xg / 5.0, 1.0) * 25
        + min(combined_sot / 12.0, 1.0) * 20
        + min(over15, 1.0) * 25
    )
    features["goal_pressure_profile"] = round(max(0.0, min(100.0, pressure)), 6)
    late_proxy = min(1.0, max(0.0, second_half * 0.75 + min(first_goal / 60.0, 1.0) * 0.25))
    features["late_goal_risk_proxy"] = round(late_proxy * 100.0, 6)


def _quality(features: dict[str, float], feature_columns: list[str], home_count: int, away_count: int, pre_match_count: int) -> dict[str, Any]:
    payload = {column: _safe_float(features.get(column), 0.0) for column in feature_columns}
    non_zero = sum(1 for value in payload.values() if abs(value) > 1e-12)
    expected = len(feature_columns)
    coverage = non_zero / expected if expected else 0.0
    # A zero is often a legitimate football value (for example zero points or
    # zero draws), so critical availability must be based on history presence,
    # not on whether the computed value happens to be non-zero.
    critical_missing: list[str] = []
    if home_count == 0:
        critical_missing.extend(["home_team_last_5_goals_for", "home_team_last_5_points"])
    if away_count == 0:
        critical_missing.extend(["away_team_last_5_goals_for", "away_team_last_5_points"])
    if min(home_count, away_count) == 0:
        critical_missing.append("combined_team_last_5_over_1_5")
    passed = (
        min(home_count, away_count) >= settings.minimum_team_history
        and coverage >= settings.minimum_feature_coverage
        and not critical_missing
    )
    return {
        "expected_features": expected,
        "non_zero_features": non_zero,
        "coverage_ratio": round(coverage, 6),
        "critical_features_missing": critical_missing,
        "home_prior_matches": home_count,
        "away_prior_matches": away_count,
        "min_team_matches_before": min(home_count, away_count),
        "odds_available": bool(payload.get("odds_ft_home_team_win") and payload.get("odds_ft_draw") and payload.get("odds_ft_away_team_win")),
        "pre_match_fields_available": pre_match_count,
        "leakage_safe": True,
        "passed": passed,
    }


def _build_one_feature_row(
    league_slug: str,
    fixture: dict[str, Any],
    appearances: list[dict[str, Any]],
    feature_columns: list[str],
) -> dict[str, Any]:
    raw = _raw_match(fixture)
    normalized = normalize_footystats_match(raw)
    fixture_dt = _match_datetime(raw)
    if pd.isna(fixture_dt):
        fixture_dt = _parse_date(normalized.get("kickoff_time") or normalized.get("match_date"))

    home = normalized.get("home_team") or ""
    away = normalized.get("away_team") or ""
    prior = [row for row in appearances if not pd.isna(row["date"]) and row["date"] < fixture_dt]
    home_key = _team_key(home)
    away_key = _team_key(away)
    home_history = [row for row in prior if row.get("team_key", _team_key(row.get("team"))) == home_key]
    away_history = [row for row in prior if row.get("team_key", _team_key(row.get("team"))) == away_key]

    features: dict[str, float] = {}
    _add_team_features(features, "home", home_history)
    _add_team_features(features, "away", away_history)
    _add_combined_features(features)
    _add_odds_features(features, raw)
    pre_match_count = _add_pre_match_features(features, raw)
    _add_derived_profiles(features)

    feature_payload = {column: _safe_float(features.get(column), 0.0) for column in feature_columns}
    meta = _quality(feature_payload, feature_columns, len(home_history), len(away_history), pre_match_count)

    return {
        "match_external_id": normalized.get("match_external_id") or str(_first(raw, ["id", "match_id", "fixture_id"], "")),
        "match_date": normalized.get("match_date") or (fixture_dt.date().isoformat() if not pd.isna(fixture_dt) else ""),
        "kickoff_time": normalized.get("kickoff_time") or (fixture_dt.tz_localize("UTC").isoformat().replace("+00:00", "Z") if not pd.isna(fixture_dt) else None),
        "home_team": home,
        "away_team": away,
        "league_slug": league_slug,
        "features": feature_payload,
        "feature_meta": meta,
    }


def build_live_feature_rows_from_footystats(
    league_slug: str,
    fixtures: list[dict[str, Any]],
    completed_matches: list[dict[str, Any]],
    feature_columns: list[str],
) -> list[dict[str, Any]]:
    appearances = _completed_to_appearances(completed_matches)
    return [_build_one_feature_row(league_slug, fixture, appearances, feature_columns) for fixture in fixtures]


def build_minimal_feature_rows_from_footystats(
    league_slug: str,
    fixtures: list[dict[str, Any]],
    feature_columns: list[str],
) -> list[dict[str, Any]]:
    return build_live_feature_rows_from_footystats(league_slug, fixtures, [], feature_columns)


def dataframe_to_feature_rows(df: pd.DataFrame, league_slug: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        match_date = str(row.get("Date", row.get("match_date", "")))[:10]
        home = str(row.get("HomeTeam", row.get("home_team", "")))
        away = str(row.get("AwayTeam", row.get("away_team", "")))
        meta = {"Date", "match_date", "HomeTeam", "AwayTeam", "home_team", "away_team", "match_external_id", "kickoff_time"}
        features = {key: value for key, value in row.to_dict().items() if key not in meta}
        non_zero = sum(1 for value in features.values() if _safe_float(value) != 0.0)
        rows.append(
            {
                "match_external_id": str(row.get("match_external_id", f"{match_date}_{home}_{away}")),
                "match_date": match_date,
                "kickoff_time": str(row.get("kickoff_time", match_date)),
                "home_team": home,
                "away_team": away,
                "league_slug": league_slug,
                "features": features,
                "feature_meta": {
                    "expected_features": len(features),
                    "non_zero_features": non_zero,
                    "coverage_ratio": non_zero / len(features) if features else 0.0,
                    "leakage_safe": True,
                    "passed": bool(features and non_zero > 0),
                },
            }
        )
    return rows
