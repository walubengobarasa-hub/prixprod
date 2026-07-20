from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings


_COMPLETED_STATUSES = {
    "complete",
    "completed",
    "finished",
    "full time",
    "ft",
    "after extra time",
    "aet",
    "after penalties",
    "penalties",
    "awarded",
}

_CANCELLED_STATUSES = {
    "cancelled",
    "canceled",
    "postponed",
    "abandoned",
    "suspended",
}


def normalize_match_status(value: Any) -> str:
    return " ".join(
        str(value or "")
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )


def is_completed_status(value: Any) -> bool:
    return normalize_match_status(value) in _COMPLETED_STATUSES


def is_cancelled_status(value: Any) -> bool:
    return normalize_match_status(value) in _CANCELLED_STATUSES


def first(d: dict[str, Any], keys: list[str], default=None):
    for key in keys:
        if key in d and d[key] is not None and d[key] != "":
            return d[key]
    return default


def _parse_datetime(m: dict[str, Any]) -> datetime | None:
    ts = first(m, ["date_unix", "timestamp", "kickoff_unix", "unix_timestamp"], None)
    if ts is not None:
        try:
            return datetime.fromtimestamp(int(float(ts)), tz=timezone.utc)
        except Exception:
            pass
    value = first(m, ["date", "match_date", "kickoff", "kickoff_time"], None)
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None


def normalize_footystats_match(m: dict[str, Any]) -> dict[str, Any]:
    home = first(m, ["home_name", "homeTeam", "home_team_name", "home_team", "HomeTeam", "team_a_name"], "")
    away = first(m, ["away_name", "awayTeam", "away_team_name", "away_team", "AwayTeam", "team_b_name"], "")
    dt = _parse_datetime(m)
    kickoff_time = dt.isoformat().replace("+00:00", "Z") if dt else None
    match_date = (
        dt.astimezone(ZoneInfo(settings.platform_timezone)).date().isoformat()
        if dt
        else str(first(m, ["date", "match_date"], ""))[:10]
    )
    return {
        "match_external_id": str(first(m, ["id", "match_id", "fixture_id"], "")),
        "match_date": match_date,
        "kickoff_time": kickoff_time,
        "home_team": str(home or ""),
        "away_team": str(away or ""),
        "status": str(first(m, ["status", "match_status"], "scheduled")).lower(),
        "raw": m,
    }


def split_completed_and_fixtures(matches: list[dict[str, Any]], target_date: str | None = None):
    completed: list[dict[str, Any]] = []
    fixtures: list[dict[str, Any]] = []
    for match in matches:
        normalized = normalize_footystats_match(match)
        status = normalized.get("status", "")
        if is_completed_status(status):
            completed.append(match)
        elif target_date is None or normalized.get("match_date") == target_date:
            fixtures.append(match)
    return completed, fixtures


def _score_value(match: dict[str, Any], keys: list[str]) -> int | None:
    value = first(match, keys, None)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_fixture_result(match: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_footystats_match(match)
    raw_status = first(match, ["status", "match_status"], normalized.get("status", "scheduled"))
    status_text = normalize_match_status(raw_status)
    home_score = _score_value(match, [
        "homeGoalCount", "home_goal_count", "home_goals", "home_score",
        "homeTeamScore", "team_a_score", "goals_home", "score_home",
    ])
    away_score = _score_value(match, [
        "awayGoalCount", "away_goal_count", "away_goals", "away_score",
        "awayTeamScore", "team_b_score", "goals_away", "score_away",
    ])

    if is_cancelled_status(status_text):
        result_status = "cancelled"
    elif is_completed_status(status_text) and home_score is not None and away_score is not None:
        result_status = "completed"
    elif is_completed_status(status_text):
        result_status = "unavailable"
    else:
        result_status = "pending"

    outcome = None
    total_goals = None
    result_text = None
    if home_score is not None and away_score is not None:
        total_goals = home_score + away_score
        outcome = "HOME" if home_score > away_score else ("AWAY" if away_score > home_score else "DRAW")
        result_text = f"{home_score}-{away_score}"

    return {
        **normalized,
        "status": result_status,
        "source_status": status_text,
        "home_score": home_score,
        "away_score": away_score,
        "total_goals": total_goals,
        "outcome": outcome,
        "result_text": result_text,
    }
