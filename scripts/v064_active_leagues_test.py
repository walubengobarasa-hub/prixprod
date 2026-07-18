#!/usr/bin/env python3
"""Validate all PrixPredictor v0.6.4 league models and run a current-date live test.

Examples:
    python scripts/v064_active_leagues_test.py --force
    python scripts/v064_active_leagues_test.py --date 2026-07-18 --days 3 --api-url http://127.0.0.1:8000 --force
    python scripts/v064_active_leagues_test.py --skip-live
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import sklearn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BASELINE_LEAGUES = [
    "epl", "spain", "italy", "germany", "france", "portugal", "belgium", "brazil",
    "turkey", "scotland", "switzerland", "poland", "japan", "saudi", "norway", "ireland",
    "canada", "chile", "china", "ecuador", "estonia", "finland", "iceland", "korea",
    "latvia", "lithuania", "allsvenskan", "uruguay",
]
EXPECTED_CANONICAL_LEAGUES = 28
ACTIVE_MARKETS = {"double_chance", "over_1_5", "match_outcome"}
REVIEW_ONLY_MARKETS = {"btts", "over_2_5"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Africa/Nairobi")).date().isoformat())
    parser.add_argument("--api-url", default=os.getenv("PRIX_MODEL_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.getenv("PRIX_MODEL_API_KEY", ""))
    parser.add_argument("--days", type=int, default=0, help="Future days to include; 3 tests today through today + 3.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--include-ineligible", action="store_true")
    parser.add_argument("--minimum-feature-coverage", type=float, default=0.15)
    parser.add_argument("--report", default="data/test_reports/v064_active_leagues_latest.json")
    return parser.parse_args()


def static_validation() -> dict:
    from app.league_registry import league_registry
    from app.model_registry import model_registry

    registered = league_registry.enabled_slugs()
    missing_expected = sorted(set(BASELINE_LEAGUES) - set(registered))
    extra = sorted(set(registered) - set(BASELINE_LEAGUES))
    model_results = model_registry.validate_all()
    model_by_slug = {row["league_slug"]: row for row in model_results}

    failures: list[str] = []
    if sklearn.__version__ != "1.6.1":
        failures.append(f"scikit-learn is {sklearn.__version__}; deployment must use 1.6.1")
    registry_errors = league_registry.validate()
    if registry_errors:
        failures.extend(["registry: " + error for error in registry_errors])
    if missing_expected:
        failures.append("missing baseline league registry entries: " + ", ".join(missing_expected))
    if len(registered) != EXPECTED_CANONICAL_LEAGUES:
        failures.append(f"registry contains {len(registered)} canonical leagues; expected {EXPECTED_CANONICAL_LEAGUES}")
    for slug in registered:
        row = model_by_slug.get(slug, {})
        if not row.get("ok"):
            failures.append(f"{slug}: {row.get('error') or 'model validation failed'}")
        if row.get("feature_count", 0) <= 0:
            failures.append(f"{slug}: feature contract is empty")

    return {
        "sklearn_version": sklearn.__version__,
        "baseline_list_count": len(BASELINE_LEAGUES),
        "expected_canonical_leagues": EXPECTED_CANONICAL_LEAGUES,
        "registered_count": len(registered),
        "registered_leagues": registered,
        "missing_expected": missing_expected,
        "extra_registered": extra,
        "registry_errors": registry_errors,
        "models": model_results,
        "failures": failures,
    }


def live_validation(args: argparse.Namespace) -> dict:
    headers = {"Accept": "application/json"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key
    from app.league_registry import league_registry
    registered_leagues = league_registry.enabled_slugs()
    if args.days < 0:
        raise ValueError("--days cannot be negative")
    date_to = (datetime.fromisoformat(args.date).date() + timedelta(days=args.days)).isoformat()
    response = requests.post(
        args.api_url.rstrip("/") + "/predict/eligible",
        headers=headers,
        json={
            "leagues": registered_leagues,
            "date_from": args.date,
            "date_to": date_to,
            "force_refresh": args.force,
            "include_ineligible": args.include_ineligible,
        },
        timeout=3600,
    )
    response.raise_for_status()
    payload = response.json()
    failures: list[str] = []
    warnings: list[str] = list(payload.get("warnings") or [])

    summaries = payload.get("league_summaries") or []
    summary_slugs = {row.get("league_slug") for row in summaries}
    for slug in registered_leagues:
        if slug not in summary_slugs:
            failures.append(f"{slug}: missing live league summary")
    for row in summaries:
        slug = row.get("league_slug", "unknown")
        status = row.get("status")
        if status in {"failed", "model_unavailable", "feature_failure", "stale_season"}:
            failures.append(f"{slug}: {status}: {row.get('error') or row.get('warnings')}")
        elif status == "no_fixtures":
            warnings.append(f"{slug}: no fixtures from {args.date} through {date_to}")
        if int(row.get("feature_rows") or 0) > 0 and float(row.get("average_feature_coverage") or 0) < args.minimum_feature_coverage:
            failures.append(f"{slug}: average feature coverage below {args.minimum_feature_coverage:.0%}")

    candidates = payload.get("eligible_candidates") or []
    per_ticket_fixture_keys: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        market = candidate.get("market")
        if not candidate.get("ticket_eligible"):
            failures.append(f"{candidate.get('prediction_key')}: eligible endpoint returned ineligible candidate")
        if market not in ACTIVE_MARKETS:
            failures.append(f"{candidate.get('prediction_key')}: prohibited eligible market {market}")
        if market in REVIEW_ONLY_MARKETS:
            failures.append(f"{candidate.get('prediction_key')}: review-only market was eligible")
        if not candidate.get("explanation") or not candidate.get("reason_codes"):
            failures.append(f"{candidate.get('prediction_key')}: explanation response shape incomplete")
        if "selected" not in str(candidate.get("explanation", "")).lower():
            failures.append(f"{candidate.get('prediction_key')}: eligible explanation does not say selected")
        quality = candidate.get("feature_quality") or {}
        if not quality.get("passed"):
            failures.append(f"{candidate.get('prediction_key')}: eligible candidate failed feature quality")
        if float(quality.get("coverage_ratio") or 0) < args.minimum_feature_coverage:
            failures.append(f"{candidate.get('prediction_key')}: feature coverage below threshold")
        match_date = str(candidate.get("match_date") or "")[:10]
        if not (args.date <= match_date <= date_to):
            failures.append(f"{candidate.get('prediction_key')}: match date {match_date} is outside requested range")
        key = (str(candidate.get("match_external_id")), str(market), str(candidate.get("prediction")))
        if key in per_ticket_fixture_keys:
            failures.append(f"duplicate candidate identity in response: {key}")
        per_ticket_fixture_keys.add(key)

    return {
        "http_status": response.status_code,
        "generation_run_id": payload.get("generation_run_id"),
        "date_from": payload.get("date_from"),
        "date_to": payload.get("date_to"),
        "days_ahead": args.days,
        "league_summaries": summaries,
        "eligible_candidate_count": len(candidates),
        "reviewed_candidate_count": len(payload.get("reviewed_candidates") or []),
        "warnings": sorted(set(warnings)),
        "failures": failures,
    }


def main() -> int:
    args = parse_args()
    report = {
        "tested_at": datetime.now(ZoneInfo("Africa/Nairobi")).isoformat(),
        "target_date": args.date,
        "days_ahead": args.days,
        "baseline_leagues": BASELINE_LEAGUES,
        "static": static_validation(),
        "live": None,
    }
    if not args.skip_live:
        report["live"] = live_validation(args)

    report_path = PROJECT_ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    failures = list(report["static"].get("failures") or [])
    failures += list((report.get("live") or {}).get("failures") or [])
    print(json.dumps({
        "target_date": args.date,
        "days_ahead": args.days,
        "registered_leagues": report["static"]["registered_count"],
        "eligible_candidates": (report.get("live") or {}).get("eligible_candidate_count"),
        "failures": failures,
        "report": str(report_path),
    }, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
