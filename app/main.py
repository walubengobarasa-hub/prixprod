from __future__ import annotations

from datetime import date as date_type, datetime, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.data_adapter import is_cancelled_status, is_completed_status, normalize_fixture_result, normalize_footystats_match
from app.feature_builder import build_live_feature_rows_from_footystats
from app.footystats_client import footystats_client
from app.league_registry import league_registry
from app.model_registry import model_registry
from app.predictor import predict_feature_rows
from app.schemas import (
    EligiblePredictionRequest,
    EligiblePredictionResponse,
    FeaturePredictionRequest,
    FixtureResultsRequest,
    FixtureResultsResponse,
    FeatureRow,
    LeagueDatePredictionRequest,
    LeaguePredictionSummary,
    MockFixturePredictionRequest,
    PredictionResponse,
)
from app.security import require_api_key
from app.storage import cache_path, read_cache, write_cache

IS_PRODUCTION = settings.app_env.lower() in {"production", "prod"}
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="PrixPredictor football prediction and candidate eligibility API.",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if IS_PRODUCTION else ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Content-Type", "X-API-Key", "X-Request-ID", "X-Idempotency-Key"],
)


def _today() -> str:
    return datetime.now(ZoneInfo(settings.platform_timezone)).date().isoformat()


def _parse_date(value: str | None, fallback: str | None = None) -> str:
    raw = value or fallback or _today()
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date().isoformat()


def _date_in_range(value: str | None, date_from: str, date_to: str) -> bool:
    if not value:
        return False
    current = str(value)[:10]
    return date_from <= current <= date_to


def _cache_info(name: str) -> dict[str, Any]:
    path = cache_path(name)
    if not path.exists():
        return {"exists": False, "path": str(path), "cached_at": None}
    try:
        import json

        wrapper = json.loads(path.read_text(encoding="utf-8"))
        return {"exists": True, "path": str(path), "cached_at": wrapper.get("cached_at")}
    except Exception:
        return {"exists": True, "path": str(path), "cached_at": None}


def _registry_identifier(league_slug: str) -> tuple[dict[str, Any], str]:
    meta = league_registry.get(league_slug)
    canonical_slug = str(meta.get("alias_for") or league_slug)
    if meta.get("alias_for"):
        meta = league_registry.get(canonical_slug)
    identifier = meta.get("footystats_season_id") or meta.get("footystats_league_id")
    if not identifier:
        raise HTTPException(status_code=400, detail=f"FootyStats season/league ID is not configured for {league_slug}.")
    return meta, str(identifier)


def _cache_names(league_slug: str, identifier: str) -> dict[str, str]:
    prefix = f"live_{league_slug}_{identifier}_{settings.feature_contract_version.replace('.', '')}"
    return {
        "raw": f"{prefix}_raw_league_matches",
        "normalized": f"{prefix}_normalized_matches",
        "completed": f"{prefix}_completed",
        "fixtures": f"{prefix}_fixtures",
        "features": f"{prefix}_feature_rows",
    }


def _classify_matches(raw_matches: list[dict[str, Any]], date_from: str, date_to: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    completed: list[dict[str, Any]] = []
    fixtures: list[dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)

    for raw in raw_matches:
        normalized = normalize_footystats_match(raw)
        status = str(normalized.get("status") or "").lower()
        kickoff = normalized.get("kickoff_time")
        kickoff_dt: datetime | None = None
        if kickoff:
            try:
                kickoff_dt = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
                if kickoff_dt.tzinfo is None:
                    kickoff_dt = kickoff_dt.replace(tzinfo=timezone.utc)
            except Exception:
                kickoff_dt = None

        is_completed = is_completed_status(status)
        is_cancelled = is_cancelled_status(status)
        # A future row must never enter the historical/completed feature pool,
        # even if an upstream source supplies an inconsistent status.
        if is_completed and (kickoff_dt is None or kickoff_dt <= now_utc):
            completed.append(raw)
            continue
        if is_cancelled:
            continue
        if kickoff_dt is not None and kickoff_dt <= now_utc:
            # Never present an already-started unconfirmed row as a pre-match fixture.
            continue
        if _date_in_range(normalized.get("match_date"), date_from, date_to):
            fixtures.append(raw)
    return completed, fixtures


def _sync_league_matches(
    league_slug: str,
    date_from: str,
    date_to: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    meta, identifier = _registry_identifier(league_slug)
    raw_matches = footystats_client.league_matches(identifier, force_refresh=force_refresh)
    completed, fixtures = _classify_matches(raw_matches, date_from, date_to)

    normalized = [normalize_footystats_match(row) for row in raw_matches]
    normalized_completed = [normalize_footystats_match(row) for row in completed]
    normalized_fixtures = [normalize_footystats_match(row) for row in fixtures]
    all_dates = sorted(str(row.get("match_date"))[:10] for row in normalized if row.get("match_date"))
    completed_dates = sorted(str(row.get("match_date"))[:10] for row in normalized_completed if row.get("match_date"))
    latest_data_match_date = all_dates[-1] if all_dates else None
    latest_completed_date = completed_dates[-1] if completed_dates else None
    stale_season = False
    freshness_date = latest_completed_date or latest_data_match_date
    if freshness_date:
        try:
            stale_season = (
                date_type.fromisoformat(date_to) - date_type.fromisoformat(freshness_date)
            ).days > settings.maximum_season_staleness_days
        except Exception:
            stale_season = False
    names = _cache_names(league_slug, identifier)

    metadata = {
        "league_slug": league_slug,
        "footystats_identifier": identifier,
        "date_from": date_from,
        "date_to": date_to,
        "latest_data_match_date": latest_data_match_date,
        "latest_completed_date": latest_completed_date,
        "stale_season": stale_season,
        "feature_contract_version": settings.feature_contract_version,
    }
    write_cache(names["raw"], raw_matches, metadata=metadata)
    write_cache(names["normalized"], normalized, metadata=metadata)
    write_cache(names["completed"], normalized_completed, metadata=metadata)
    write_cache(names["fixtures"], normalized_fixtures, metadata=metadata)

    return {
        "league_slug": league_slug,
        "league_name": meta.get("display_name") or meta.get("name") or league_slug,
        "footystats_identifier": identifier,
        "date_from": date_from,
        "date_to": date_to,
        "latest_data_match_date": latest_data_match_date,
        "latest_completed_date": latest_completed_date,
        "stale_season": stale_season,
        "raw_matches": raw_matches,
        "completed_raw": completed,
        "fixtures_raw": fixtures,
        "raw_count": len(raw_matches),
        "normalized_count": len(normalized),
        "completed_count": len(completed),
        "fixture_count": len(fixtures),
        "cache": {key: _cache_info(value) for key, value in names.items() if key != "features"},
        "sample_fixture": normalized_fixtures[0] if normalized_fixtures else None,
        "sample_completed": normalized_completed[-1] if normalized_completed else None,
    }


def _build_league_features(
    league_slug: str,
    date_from: str,
    date_to: str,
    force_refresh: bool = False,
) -> tuple[dict[str, Any], list[FeatureRow]]:
    sync = _sync_league_matches(league_slug, date_from, date_to, force_refresh=force_refresh)
    loaded = model_registry.get(league_slug)
    built = build_live_feature_rows_from_footystats(
        league_slug,
        sync["fixtures_raw"],
        sync["completed_raw"],
        loaded.raw_feature_columns,
    )
    rows = [FeatureRow(**row) for row in built]
    _, identifier = _registry_identifier(league_slug)
    names = _cache_names(league_slug, identifier)
    write_cache(
        names["features"],
        [row.model_dump() for row in rows],
        metadata={
            "league_slug": league_slug,
            "date_from": date_from,
            "date_to": date_to,
            "feature_contract_version": settings.feature_contract_version,
        },
    )
    sync["feature_count"] = len(rows)
    sync["feature_cache"] = _cache_info(names["features"])
    return sync, rows


def _feature_rows_from_cache(league_slug: str) -> list[FeatureRow]:
    _, identifier = _registry_identifier(league_slug)
    rows = read_cache(_cache_names(league_slug, identifier)["features"], max_age_seconds=settings.cache_ttl_seconds) or []
    return [FeatureRow(**row) for row in rows if isinstance(row, dict)]


def _unix_from_date(value: str) -> int:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        dt = datetime.strptime(str(value)[:10], "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _mock_fixture_to_footystats_raw(payload: MockFixturePredictionRequest) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": payload.match_external_id or f"mock_{payload.home_team}_{payload.away_team}_{payload.match_date}",
        "status": "incomplete",
        "date_unix": _unix_from_date(payload.kickoff_time or payload.match_date),
        "home_name": payload.home_team,
        "away_name": payload.away_team,
    }
    for key in (
        "odds_ft_1", "odds_ft_x", "odds_ft_2", "odds_ft_over15", "odds_ft_under15",
        "odds_ft_over25", "odds_ft_under25", "odds_btts_yes", "odds_btts_no",
        "odds_doublechance_1x", "odds_doublechance_12", "odds_doublechance_x2",
    ):
        value = getattr(payload, key, None)
        if value is not None:
            raw[key] = value
    return raw


@app.get("/", include_in_schema=False)
def root() -> dict[str, Any]:
    return {
        **health(),
        "health_url": "/health",
        "models_url": "/models",
        "model_validation_url": "/models/validate",
        "eligible_predictions_url": "/predict/eligible",
        "fixture_results_url": "/results/fixtures",
        "docs_enabled": not IS_PRODUCTION,
    }




@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "api_version": "v1",
        "prediction_contract_version": settings.prediction_contract_version,
        "feature_contract_version": settings.feature_contract_version,
        "registered_leagues": len(league_registry.enabled_slugs()),
    }


@app.get("/models")
def models() -> dict[str, Any]:
    leagues: list[dict[str, Any]] = []
    for slug, original_meta in league_registry.list_leagues().items():
        meta = dict(original_meta or {})
        row: dict[str, Any] = {
            "league_slug": slug,
            "display_name": meta.get("display_name") or meta.get("name") or slug,
            "enabled": bool(meta.get("enabled", True)),
            "alias_for": meta.get("alias_for"),
            "model_folder": meta.get("model_folder") or meta.get("alias_for") or slug,
            "footystats_league_id": meta.get("footystats_league_id"),
            "footystats_season_id": meta.get("footystats_season_id"),
        }
        if not meta.get("alias_for"):
            try:
                loaded = model_registry.get(slug)
                row.update({
                    "model_version": loaded.model_version,
                    "model_mode": loaded.default_mode,
                    "feature_count": len(loaded.raw_feature_columns),
                    "fitted_feature_count": len(loaded.model_feature_columns),
                    "available_modes": loaded.available_modes(),
                    "loaded_models": {key: value is not None for key, value in loaded.models.items()},
                    "active_candidate_markets": ["double_chance", "over_1_5", "match_outcome"],
                    "review_only_markets": ["btts", "over_2_5"],
                    "explainability_enabled": bool(loaded.config.get("explainability") or loaded.explainability_profile),
                })
            except Exception as exc:
                row["error"] = str(exc)
        leagues.append(row)
    return {
        "api_version": "v1",
        "prediction_contract_version": settings.prediction_contract_version,
        "feature_contract_version": settings.feature_contract_version,
        "registry_errors": league_registry.validate(),
        "leagues": leagues,
    }


@app.post("/registry/reload", dependencies=[Depends(require_api_key)])
def reload_registry() -> dict[str, Any]:
    league_registry.reload()
    model_registry.clear()
    return {"ok": True, "registered_leagues": len(league_registry.enabled_slugs()), "errors": league_registry.validate()}


@app.get("/models/validate", dependencies=[Depends(require_api_key)])
def validate_models() -> dict[str, Any]:
    registry_errors = league_registry.validate()
    model_results = model_registry.validate_all()
    return {
        "ok": not registry_errors and all(row.get("ok") for row in model_results),
        "expected_leagues": len(league_registry.enabled_slugs()),
        "registry_errors": registry_errors,
        "models": model_results,
    }


@app.post("/models/{league_slug}/reload", dependencies=[Depends(require_api_key)])
def reload_model(league_slug: str) -> dict[str, Any]:
    try:
        loaded = model_registry.reload(league_slug)
        return {
            "league_slug": league_slug,
            "model_version": loaded.model_version,
            "model_mode": loaded.default_mode,
            "feature_count": len(loaded.raw_feature_columns),
            "available_modes": loaded.available_modes(),
            "loaded_models": {key: value is not None for key, value in loaded.models.items()},
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sync/league/{league_slug}", dependencies=[Depends(require_api_key)])
def sync_league(league_slug: str, payload: LeagueDatePredictionRequest | None = None) -> dict[str, Any]:
    request = payload or LeagueDatePredictionRequest()
    target = _parse_date(request.date)
    try:
        result = _sync_league_matches(league_slug, target, target, request.force_refresh)
        return {key: value for key, value in result.items() if key not in {"raw_matches", "completed_raw", "fixtures_raw"}}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sync/completed/{league_slug}", dependencies=[Depends(require_api_key)])
def sync_completed(league_slug: str, payload: LeagueDatePredictionRequest | None = None) -> dict[str, Any]:
    request = payload or LeagueDatePredictionRequest()
    target = _parse_date(request.date)
    try:
        result = _sync_league_matches(league_slug, target, target, request.force_refresh)
        return {
            "league_slug": league_slug,
            "completed_count": result["completed_count"],
            "sample_completed": result.get("sample_completed"),
            "cache": result.get("cache", {}).get("completed"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sync/table/{league_slug}", dependencies=[Depends(require_api_key)])
def sync_table(league_slug: str, payload: LeagueDatePredictionRequest | None = None) -> dict[str, Any]:
    request = payload or LeagueDatePredictionRequest()
    try:
        _, identifier = _registry_identifier(league_slug)
        max_time = _unix_from_date(request.date) if request.date else None
        table = footystats_client.league_table(identifier, max_time=max_time, force_refresh=request.force_refresh)
        return {"league_slug": league_slug, "footystats_identifier": identifier, "table": table}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/build-features/{league_slug}", dependencies=[Depends(require_api_key)])
def build_features(league_slug: str, payload: LeagueDatePredictionRequest | None = None) -> dict[str, Any]:
    request = payload or LeagueDatePredictionRequest()
    target = _parse_date(request.date)
    try:
        sync, rows = _build_league_features(league_slug, target, target, request.force_refresh)
        coverages = [float((row.feature_meta or {}).get("coverage_ratio", 0) or 0) for row in rows]
        return {
            "league_slug": league_slug,
            "date": target,
            "fixtures_found": sync["fixture_count"],
            "feature_rows": len(rows),
            "average_feature_coverage": round(sum(coverages) / len(coverages), 6) if coverages else 0,
            "rows": [row.model_dump() for row in rows],
            "cache": sync.get("feature_cache"),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/results/fixtures", response_model=FixtureResultsResponse, dependencies=[Depends(require_api_key)])
def fixture_results(payload: FixtureResultsRequest) -> FixtureResultsResponse:
    requested = list(payload.fixtures or [])
    if not requested:
        return FixtureResultsResponse(
            generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            requested=0,
            completed=0,
            pending=0,
            cancelled=0,
            not_found=0,
            results=[],
        )

    grouped: dict[str, list[Any]] = {}
    warnings: list[str] = []
    for reference in requested:
        grouped.setdefault(reference.league_slug, []).append(reference)

    results: list[dict[str, Any]] = []
    for requested_slug, references in grouped.items():
        try:
            original_meta = league_registry.get(requested_slug)
            canonical_slug = str(original_meta.get("alias_for") or requested_slug)
            meta, identifier = _registry_identifier(requested_slug)
            raw_matches = footystats_client.league_matches(identifier, force_refresh=payload.force_refresh)
            by_id = {
                str((row or {}).get("id") or (row or {}).get("match_id") or (row or {}).get("fixture_id") or ""): row
                for row in raw_matches if isinstance(row, dict)
            }
            for reference in references:
                raw = by_id.get(str(reference.match_external_id))
                if raw is None:
                    results.append({
                        "match_external_id": str(reference.match_external_id),
                        "league_slug": canonical_slug,
                        "league_name": meta.get("display_name") or meta.get("name") or canonical_slug,
                        "status": "not_found",
                    })
                    continue
                normalized = normalize_fixture_result(raw)
                normalized.update({
                    "match_external_id": str(reference.match_external_id),
                    "league_slug": canonical_slug,
                    "league_name": meta.get("display_name") or meta.get("name") or canonical_slug,
                })
                results.append(normalized)
        except Exception as exc:
            warnings.append(f"{requested_slug}: {exc}")
            for reference in references:
                results.append({
                    "match_external_id": str(reference.match_external_id),
                    "league_slug": requested_slug,
                    "status": "not_found",
                })

    return FixtureResultsResponse(
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        requested=len(requested),
        completed=sum(1 for row in results if row.get("status") == "completed"),
        pending=sum(1 for row in results if row.get("status") in {"pending", "unavailable"}),
        cancelled=sum(1 for row in results if row.get("status") == "cancelled"),
        not_found=sum(1 for row in results if row.get("status") == "not_found"),
        results=results,
        warnings=warnings,
    )


@app.post("/predict/features", response_model=PredictionResponse, dependencies=[Depends(require_api_key)])
def predict_features(payload: FeaturePredictionRequest) -> PredictionResponse:
    try:
        run_id = str(uuid4())
        candidates = predict_feature_rows(payload.league_slug, payload.rows, generation_run_id=run_id)
        loaded = model_registry.get(payload.league_slug)
        return PredictionResponse(
            league_slug=payload.league_slug,
            model_version=loaded.model_version,
            date=payload.date,
            candidates=candidates,
            tickets=[],
            single_match_insights=[candidate for candidate in candidates if candidate.ticket_eligible],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/predict/league/{league_slug}", response_model=PredictionResponse, dependencies=[Depends(require_api_key)])
def predict_league(league_slug: str, payload: LeagueDatePredictionRequest | None = None) -> PredictionResponse:
    request = payload or LeagueDatePredictionRequest()
    target = _parse_date(request.date)
    try:
        _, rows = _build_league_features(league_slug, target, target, request.force_refresh)
        run_id = str(uuid4())
        candidates = predict_feature_rows(league_slug, rows, generation_run_id=run_id)
        loaded = model_registry.get(league_slug)
        return PredictionResponse(
            league_slug=league_slug,
            model_version=loaded.model_version,
            date=target,
            candidates=candidates,
            tickets=[],
            single_match_insights=[candidate for candidate in candidates if candidate.ticket_eligible],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/predict/eligible", response_model=EligiblePredictionResponse, dependencies=[Depends(require_api_key)])
def predict_eligible(payload: EligiblePredictionRequest) -> EligiblePredictionResponse:
    date_from = _parse_date(payload.date_from or payload.date)
    date_to = _parse_date(payload.date_to, date_from)
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to must be on or after date_from.")

    requested = payload.leagues or league_registry.enabled_slugs()
    # Resolve aliases while preserving deterministic order and preventing duplicate model runs.
    seen: set[str] = set()
    leagues: list[str] = []
    for slug in requested:
        try:
            meta = league_registry.get(slug)
            canonical = str(meta.get("alias_for") or slug)
        except Exception:
            canonical = slug
        if canonical not in seen:
            seen.add(canonical)
            leagues.append(canonical)

    run_id = str(uuid4())
    eligible = []
    reviewed = []
    summaries: list[LeaguePredictionSummary] = []
    warnings: list[str] = []

    for league_slug in leagues:
        try:
            sync, rows = _build_league_features(
                league_slug,
                date_from,
                date_to,
                force_refresh=payload.force_refresh,
            )
            candidates = predict_feature_rows(league_slug, rows, generation_run_id=run_id)
            league_eligible = [candidate for candidate in candidates if candidate.ticket_eligible]
            eligible.extend(league_eligible)
            if payload.include_ineligible:
                reviewed.extend([candidate for candidate in candidates if not candidate.ticket_eligible])

            coverage_values = [
                float(candidate.feature_quality.coverage_ratio)
                for candidate in candidates
                if candidate.feature_quality is not None
            ]
            if sync.get("stale_season"):
                status = "stale_season"
            elif sync["fixture_count"] == 0:
                status = "no_fixtures"
            elif not rows:
                status = "feature_failure"
            elif not league_eligible:
                status = "low_volume"
            else:
                status = "healthy"
            league_warnings: list[str] = []
            if sync.get("stale_season"):
                league_warnings.append(
                    f"FootyStats data ends at {sync.get('latest_data_match_date')}; verify the current season ID."
                )
            if rows and all(not bool((row.feature_meta or {}).get("passed")) for row in rows):
                league_warnings.append("All live feature rows failed the feature-quality gate.")
                status = "feature_failure"
            summaries.append(LeaguePredictionSummary(
                league_slug=league_slug,
                league_name=sync.get("league_name"),
                footystats_identifier=sync.get("footystats_identifier"),
                status=status,
                latest_data_match_date=sync.get("latest_data_match_date"),
                latest_completed_date=sync.get("latest_completed_date"),
                fixtures_found=sync["fixture_count"],
                feature_rows=len(rows),
                candidates_generated=len(candidates),
                eligible_candidates=len(league_eligible),
                average_feature_coverage=round(sum(coverage_values) / len(coverage_values), 6) if coverage_values else 0,
                warnings=league_warnings,
            ))
        except Exception as exc:
            summaries.append(LeaguePredictionSummary(
                league_slug=league_slug,
                status="failed",
                error=str(exc),
                warnings=["This league was skipped; other leagues continued processing."],
            ))
            warnings.append(f"{league_slug}: {exc}")

    eligible.sort(key=lambda candidate: (candidate.match_date, candidate.kickoff_time or "", -candidate.confidence_score, candidate.league_slug))
    reviewed.sort(key=lambda candidate: (candidate.match_date, candidate.kickoff_time or "", candidate.league_slug, candidate.market))
    return EligiblePredictionResponse(
        generation_run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        date_from=date_from,
        date_to=date_to,
        requested_leagues=leagues,
        eligible_candidates=eligible,
        reviewed_candidates=reviewed,
        league_summaries=summaries,
        warnings=warnings,
        prediction_contract_version=settings.prediction_contract_version,
        feature_contract_version=settings.feature_contract_version,
        candidate_rule_version=settings.candidate_rule_version,
    )


@app.post("/predict/mock-fixture/{league_slug}", response_model=PredictionResponse, dependencies=[Depends(require_api_key)])
def predict_mock_fixture(league_slug: str, payload: MockFixturePredictionRequest) -> PredictionResponse:
    target = _parse_date(payload.match_date)
    try:
        sync = _sync_league_matches(league_slug, target, target, force_refresh=False)
        loaded = model_registry.get(league_slug)
        raw_fixture = _mock_fixture_to_footystats_raw(payload)
        built = build_live_feature_rows_from_footystats(
            league_slug,
            [raw_fixture],
            sync["completed_raw"],
            loaded.raw_feature_columns,
        )
        rows = [FeatureRow(**row) for row in built]
        run_id = str(uuid4())
        candidates = predict_feature_rows(league_slug, rows, generation_run_id=run_id)
        return PredictionResponse(
            league_slug=league_slug,
            model_version=loaded.model_version,
            date=target,
            candidates=candidates,
            tickets=[],
            single_match_insights=[candidate for candidate in candidates if candidate.ticket_eligible],
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
