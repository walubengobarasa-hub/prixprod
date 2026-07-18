from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from app.config import settings
from app.model_registry import model_registry
from app.schemas import EligibilityEvidence, FeatureQuality, FeatureRow, PredictionCandidate

OUTCOME_ALIASES = {
    "H": "HOME_WIN",
    "HOME": "HOME_WIN",
    "HOME_WIN": "HOME_WIN",
    "2": "HOME_WIN",
    2: "HOME_WIN",
    "A": "AWAY_WIN",
    "AWAY": "AWAY_WIN",
    "AWAY_WIN": "AWAY_WIN",
    "0": "AWAY_WIN",
    0: "AWAY_WIN",
    "D": "DRAW",
    "DRAW": "DRAW",
    "1": "DRAW",
    1: "DRAW",
}

ACTIVE_MARKETS = {"double_chance", "over_1_5", "match_outcome"}
REVIEW_ONLY_MARKETS = {"btts", "over_2_5"}

ODDS_KEYS = {
    "odds_ft_home_team_win",
    "odds_ft_draw",
    "odds_ft_away_team_win",
    "odds_ft_over15",
    "odds_ft_over25",
    "odds_btts_yes",
    "odds_btts_no",
    "odds_ft_1",
    "odds_ft_x",
    "odds_ft_2",
    "BbAvH",
    "BbAvD",
    "BbAvA",
}


def sf(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        if np.isnan(result) or np.isinf(result):
            return default
        return result
    except Exception:
        return default


def pred_bin(model, frame, index: int = 1):
    if model is None:
        return np.full(len(frame), 0.5)
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(frame)
        if getattr(proba, "ndim", 1) == 2 and proba.shape[1] > index:
            return proba[:, index]
        if getattr(proba, "ndim", 1) == 2 and proba.shape[1] == 1:
            return proba[:, 0]
    return np.asarray(model.predict(frame), dtype=float)


def _normalise_outcome_class(label: Any) -> str:
    if label in OUTCOME_ALIASES:
        return OUTCOME_ALIASES[label]
    text = str(label).strip().upper()
    return OUTCOME_ALIASES.get(text, text)


def pred_outcome(model, frame):
    fallback = ["AWAY_WIN", "DRAW", "HOME_WIN"]
    if model is None:
        return fallback, np.tile(np.array([[0.33, 0.25, 0.42]]), (len(frame), 1))
    raw_classes = getattr(model, "classes_", None)
    if raw_classes is None:
        estimator = getattr(model, "estimator", None) or getattr(model, "base_estimator", None)
        raw_classes = getattr(estimator, "classes_", fallback)
    classes = [_normalise_outcome_class(item) for item in list(raw_classes)]
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(frame)
    else:
        predicted = model.predict(frame)
        probabilities = np.zeros((len(predicted), len(classes)))
        for idx, value in enumerate(predicted):
            label = _normalise_outcome_class(value)
            if label in classes:
                probabilities[idx, classes.index(label)] = 1
    if len(classes) == 3 and not set(classes).intersection({"HOME_WIN", "DRAW", "AWAY_WIN"}):
        classes = fallback
    return classes, probabilities


def has_odds(features: dict[str, Any]) -> bool:
    return any(key in features and sf(features.get(key), 0) > 0 for key in ODDS_KEYS)


def choose_model_mode(loaded_model, features: dict[str, Any]) -> str:
    modes = set(loaded_model.available_modes())
    if {"football_only", "odds_aware"}.intersection(modes):
        return "odds_aware" if "odds_aware" in modes and has_odds(features) else "football_only"
    return loaded_model.default_mode


def score_over15(over_probability: float, under_probability: float, features: dict[str, Any]):
    confidence = (0.72 * over_probability + 0.28 * (1 - under_probability)) * 100
    risk = under_probability * 100
    note = ""
    btts = sf(features.get("btts_yes_proxy", features.get("btts_prob", 0.55)), 0.55)
    favorite_win = sf(features.get("outcome_favorite_win_prob_proxy", features.get("favorite_win_prob", 0)), 0)
    favorite_avoid = sf(features.get("outcome_favorite_avoid_prob_proxy", features.get("favorite_avoid_prob", 0)), 0)
    if favorite_win >= 0.78 and favorite_avoid >= 0.86 and btts <= 0.52:
        confidence -= 8
        risk += 7
        note = "Controlled-favorite goal-risk adjustment applied."
    elif favorite_win >= 0.72 and favorite_avoid >= 0.84 and btts <= 0.47:
        confidence -= 5
        risk += 5
        note = "Low-tempo favorite adjustment applied."
    return round(max(0, min(confidence, 100)), 6), round(max(0, min(risk, 100)), 6), note


def score_over25(over_probability: float, under_probability: float, features: dict[str, Any]):
    goal_pressure = sf(features.get("goal_pressure_profile"), 55) / 100.0
    confidence = (0.64 * over_probability + 0.26 * (1 - under_probability) + 0.10 * goal_pressure) * 100
    risk = max(under_probability * 100, 100 - over_probability * 100)
    return round(max(0, min(confidence, 100)), 6), round(max(0, min(risk, 100)), 6)


def score_outcome(top_probability: float, draw_risk_probability: float, favorite_win: float, favorite_avoid: float, agreement: float):
    draw_risk = draw_risk_probability * 100
    confidence = (
        0.48 * top_probability * 100
        + 0.20 * favorite_win * 100
        + 0.17 * favorite_avoid * 100
        + 0.15 * agreement
        - max(0, draw_risk - 20) * 0.35
    )
    return round(max(0, min(confidence, 100)), 6), round(max(0, min(draw_risk, 100)), 6)


def score_double_chance(probability: float, draw_risk: float, favorite_avoid: float, agreement: float):
    risk = max(0, 100 - probability * 100)
    confidence = 0.62 * probability * 100 + 0.18 * favorite_avoid * 100 + 0.10 * agreement + 0.10 * (100 - draw_risk)
    return round(max(0, min(confidence, 100)), 6), round(max(0, min(risk, 100)), 6)


def _market_rule(config: dict[str, Any], market: str) -> dict[str, Any]:
    return dict((config.get("market_rules") or {}).get(market) or {})


def _market_status(config: dict[str, Any], market: str) -> str:
    if market in REVIEW_ONLY_MARKETS:
        return "review_only"
    if market == "match_outcome":
        return "active"
    rule = _market_rule(config, market)
    status = str(rule.get("status", "active")).strip().lower()
    if status in {"active_pending_threshold_review", "active_candidate", "candidate", "enabled"}:
        return "active"
    return status


def tier_for(market: str, confidence: float, config: dict[str, Any]) -> str:
    rule = _market_rule(config, market)
    if _market_status(config, market) == "review_only":
        return "review"
    if confidence >= sf(rule.get("elite_threshold"), 999):
        return "elite"
    if confidence >= sf(rule.get("premium_threshold"), 999):
        return "premium"
    if confidence >= sf(rule.get("public_threshold"), 999):
        return "public"
    return "hidden"


def _feature_quality(row: FeatureRow) -> FeatureQuality:
    meta = dict(row.feature_meta or {})
    features = row.features or {}
    expected = int(meta.get("expected_features") or len(features))
    non_zero = int(meta.get("non_zero_features") or sum(1 for value in features.values() if abs(sf(value)) > 1e-12))
    ratio = sf(meta.get("coverage_ratio"), non_zero / expected if expected else 0.0)
    home_history = int(meta.get("home_prior_matches") or meta.get("home_history") or 0)
    away_history = int(meta.get("away_prior_matches") or meta.get("away_history") or 0)
    min_history = int(meta.get("min_team_matches_before") or min(home_history, away_history))
    provided_pass = meta.get("passed")
    passed = bool(provided_pass) if provided_pass is not None else bool(non_zero > 0 and ratio >= 0.15)
    return FeatureQuality(
        expected_features=expected,
        non_zero_features=non_zero,
        coverage_ratio=round(ratio, 6),
        critical_features_missing=list(meta.get("critical_features_missing") or []),
        home_prior_matches=home_history,
        away_prior_matches=away_history,
        min_team_matches_before=min_history,
        odds_available=bool(meta.get("odds_available", has_odds(features))),
        pre_match_fields_available=int(meta.get("pre_match_fields_available") or 0),
        leakage_safe=bool(meta.get("leakage_safe", True)),
        passed=passed,
    )


def _odds_favorite(features: dict[str, Any]) -> str | None:
    home = sf(features.get("odds_home_prob"), 0)
    draw = sf(features.get("odds_draw_prob"), 0)
    away = sf(features.get("odds_away_prob"), 0)
    if home <= 0 and draw <= 0 and away <= 0:
        return None
    if home > draw and home >= away:
        return "HOME"
    if away > draw and away > home:
        return "AWAY"
    return None


def evaluate_eligibility(
    market: str,
    candidate: dict[str, Any],
    config: dict[str, Any],
    quality: FeatureQuality,
) -> tuple[bool, EligibilityEvidence, str]:
    rule = _market_rule(config, market)
    checks: dict[str, bool] = {}
    failures: list[str] = []

    def check(name: str, passed: bool, failure: str):
        checks[name] = bool(passed)
        if not passed:
            failures.append(failure)

    status = _market_status(config, market)
    check("market_active", market in ACTIVE_MARKETS and status not in {"review_only", "paused", "disabled"}, f"{market} is review-only or disabled.")
    check("feature_quality_passed", quality.passed, "Live feature coverage did not meet the publishing threshold.")
    check("leakage_safe", quality.leakage_safe, "Feature row failed the pre-match leakage guard.")

    public_threshold = sf(rule.get("public_threshold"), 86 if market == "match_outcome" else 999)
    check("confidence_passed", sf(candidate.get("confidence_score")) >= public_threshold, f"{market} confidence is below {public_threshold:.1f}.")

    max_risk = rule.get("public_max_risk", rule.get("max_risk_public"))
    if max_risk is not None:
        check("risk_passed", sf(candidate.get("risk_score"), 999) <= sf(max_risk, 999), f"{market} risk is above the configured maximum.")
    else:
        checks["risk_passed"] = True

    if market == "over_1_5":
        max_under = sf(rule.get("max_under15_risk_prob", rule.get("max_under15_risk_public", 0.25)), 0.25)
        check("under15_risk_passed", sf(candidate.get("under15_risk_prob"), 1) <= max_under, "Over 1.5 Under 1.5 risk is too high.")

    if market == "double_chance":
        max_draw = sf(rule.get("max_draw_risk", rule.get("public_max_draw_risk", 36)), 36)
        min_avoid = sf(rule.get("public_min_favorite_avoid_prob", rule.get("min_favorite_avoid_prob", 0.70)), 0.70)
        min_agreement = sf(rule.get("min_agreement", 50), 50)
        favorite_side = candidate.get("favorite_side")
        prediction = str(candidate.get("prediction") or "")
        selected_side = "HOME" if prediction == "1X" else ("AWAY" if prediction == "X2" else None)
        check("draw_risk_passed", sf(candidate.get("draw_risk_score"), 100) <= max_draw, "Double Chance draw-risk support is too weak.")
        check("favorite_avoid_defeat_passed", sf(candidate.get("favorite_avoid_prob"), 0) >= min_avoid, "Double Chance avoid-defeat support is too low.")
        check("agreement_passed", sf(candidate.get("agreement_score"), 0) >= min_agreement, "Double Chance model agreement is too low.")
        # When odds identify a clear favorite, the avoid-defeat support model must
        # be applied to that same side rather than to the opposing team.
        check("favorite_side_agrees", favorite_side not in {"HOME", "AWAY"} or favorite_side == selected_side, "Double Chance selection does not agree with the pre-match favorite.")

    if market == "match_outcome":
        max_draw = sf(rule.get("public_max_draw_risk", rule.get("max_draw_risk_public", 28)), 28)
        min_agreement = sf(rule.get("min_agreement_public", rule.get("min_agreement", 60)), 60)
        min_favorite_win = sf(rule.get("min_favorite_win_prob", 0.72), 0.72)
        min_favorite_avoid = sf(rule.get("min_favorite_avoid_prob", 0.84), 0.84)
        prediction = str(candidate.get("prediction") or "")
        favorite_side = candidate.get("favorite_side")
        check("non_draw_prediction", prediction in {"HOME", "AWAY"}, "Draw Match Outcome is not publishable.")
        check("draw_risk_passed", sf(candidate.get("draw_risk_score"), 100) <= max_draw, "Match Outcome draw risk is too high.")
        check("agreement_passed", sf(candidate.get("agreement_score"), 0) >= min_agreement, "Match Outcome agreement is too low.")
        check("favorite_win_support_passed", sf(candidate.get("favorite_win_prob"), 0) >= min_favorite_win, "Favorite-win support is too low.")
        check("favorite_avoid_defeat_passed", sf(candidate.get("favorite_avoid_prob"), 0) >= min_favorite_avoid, "Favorite avoid-defeat support is too low.")
        check("market_favorite_available", favorite_side in {"HOME", "AWAY"}, "No clear pre-match favorite was available.")
        check("favorite_side_agrees", favorite_side == prediction, "Predicted winner does not agree with the pre-match favorite.")

    passed = not failures
    evidence = EligibilityEvidence(
        passed=passed,
        rule_version=settings.candidate_rule_version,
        checks=checks,
        failed_reasons=failures,
    )
    return passed, evidence, failures[0] if failures else ""


def _friendly_feature_name(name: str) -> str:
    text = str(name or "").replace("_", " ").replace("pct", "percentage").strip()
    replacements = {
        "combined team": "combined teams",
        "last 5": "recent 5-match",
        "last 10": "recent 10-match",
        "last 3": "recent 3-match",
        "sot": "shots on target",
        "xg": "expected goals",
        "ppg": "points per game",
        "btts": "both teams scoring",
        "over15": "over 1.5",
        "under15": "under 1.5",
        "goal diff": "goal difference",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return " ".join(text.split()).capitalize()


def _top_factors(loaded_model, market: str, features: dict[str, Any], max_count: int = 6) -> list[dict[str, Any]]:
    importance_aliases = {
        "over_1_5": ["over_1_5", "over15"],
        "over_2_5": ["over_2_5", "over25"],
        "btts": ["btts"],
        "match_outcome": ["match_outcome", "outcome"],
        # Double Chance is derived from the favorite-avoid-defeat and outcome support models.
        "double_chance": ["double_chance", "favorite_avoid_defeat", "avoid_defeat", "outcome"],
    }
    rows = []
    for alias in importance_aliases.get(market, [market]):
        rows = loaded_model.feature_importances.get(alias) or []
        if rows:
            break
    out: list[dict[str, Any]] = []
    normalized = {str(key): value for key, value in features.items()}
    for item in rows:
        feature = item.get("feature") or item.get("raw_feature")
        if not feature:
            continue
        value = normalized.get(str(feature))
        importance = sf(item.get("importance"), 0)
        out.append(
            {
                "feature": str(feature),
                "label": _friendly_feature_name(str(feature)),
                "value": round(sf(value), 6) if value is not None else None,
                "importance": round(importance, 6),
                "direction": "supports",
                "impact": "high" if importance >= 3 else ("medium" if importance >= 1 else "supporting"),
            }
        )
        if len(out) >= max_count:
            break
    return out


def _reason_codes(market: str, confidence: float, extras: dict[str, Any], eligible: bool) -> list[str]:
    codes: list[str] = []
    if market == "over_1_5":
        codes.extend(["strong_goal_pressure_profile", "under15_risk_checked"])
    elif market == "double_chance":
        codes.extend(["avoid_defeat_profile", "draw_risk_from_market_is_moderate"])
    elif market == "match_outcome":
        codes.extend(["market_supports_clear_favorite", "favorite_win_support_checked", "favorite_avoid_defeat_checked"])
    elif market == "btts":
        codes.append("btts_review_signal")
    elif market == "over_2_5":
        codes.append("over25_review_signal")
    if confidence >= 88:
        codes.append("elite_confidence_band")
    elif confidence >= 84:
        codes.append("premium_confidence_band")
    else:
        codes.append("public_confidence_band")
    codes.append("publishing_threshold_passed" if eligible else "publishing_threshold_not_met")
    return list(dict.fromkeys(codes))


def _explanation(market: str, prediction: str, eligible: bool, top_factors: list[dict[str, Any]]) -> str:
    if eligible:
        if market == "over_1_5":
            text = "PrixPredictor AI selected Over 1.5 after the goal-pressure profile and Under 1.5 risk checks passed."
        elif market == "double_chance":
            text = f"PrixPredictor AI selected Double Chance {prediction} because the outcome distribution and avoid-defeat support passed the publishing rules."
        elif market == "match_outcome":
            text = f"PrixPredictor AI selected Match Outcome {prediction} after confidence, draw risk, favorite-win support, avoid-defeat support, and market agreement all passed."
        else:
            text = f"PrixPredictor AI selected this {market.replace('_', ' ')} prediction after the publishing rules passed."
    else:
        text = "PrixPredictor AI reviewed this pick, but it did not meet the publishing threshold."
    if top_factors:
        labels = [factor.get("label") or factor.get("feature") for factor in top_factors[:3]]
        labels = [str(label) for label in labels if label]
        if labels:
            text += " Key factors: " + "; ".join(labels) + "."
    text += " Timing estimates are based on historical profiles and are not guarantees."
    return text


def _predict_class_label(model, frame, fallback: str | None = None) -> str | None:
    if model is None:
        return fallback
    try:
        predicted = model.predict(frame)
        if len(predicted):
            return str(predicted[0])
    except Exception:
        return fallback
    return fallback


def _timing_estimates(models: dict[str, Any], frame, features: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    first = _predict_class_label(models.get("first_goal_window"), frame, None)
    winner = _predict_class_label(models.get("winner_decision_window"), frame, None)
    first_map = {
        "0": "around the opening 15 minutes",
        "1": "around minutes 16-35",
        "2": "around minutes 36-60",
        "3": "during the later stages",
        "early": "during the opening phase",
        "early_or_first_half": "during the first half",
        "mid": "around the middle phase",
        "mid_match": "around the middle phase",
        "late": "during the later stages",
        "late_second_half": "during the later second half",
        "no_goal": "no clear first-goal window",
        "unknown": "no clear first-goal window",
    }
    winner_map = {
        "0": "during the first half",
        "1": "before the final third",
        "2": "during the second half",
        "3": "during the late match phase",
        "early": "during the early match phase",
        "early_or_first_half": "during the first half",
        "mid": "around the middle phase",
        "mid_match": "around the middle phase",
        "late": "during the late match phase",
        "late_second_half": "during the later second half",
        "draw_no_winner": "no clear winner-control window",
        "unknown_decision": "no clear winner-control window",
        "unknown": "no clear winner-control window",
    }
    first_key = str(first).lower().replace("-", "_").replace(" ", "_") if first is not None else "unknown"
    winner_key = str(winner).lower().replace("-", "_").replace(" ", "_") if winner is not None else "unknown"
    profile = round(max(0, min(100, sf(features.get("goal_pressure_profile"), 50))) / 10, 3)
    first_confidence = "medium" if profile >= 5 else "low"
    winner_confidence = "low"
    return (
        {
            "first_goal_window": first_map.get(first_key, "no clear first-goal window"),
            "confidence": first_confidence,
            "profile_score": profile,
            "reason": "Soft estimate from lagged scoring and goal-timing profiles.",
        },
        {
            "likely_decision_window": winner_map.get(winner_key, "no clear winner-control window"),
            "confidence": winner_confidence,
            "reason": "Soft match-control estimate from outcome agreement, draw risk, and historical profiles.",
        },
    )


def _prediction_key(fixture_id: str | None, market: str, prediction: str, model_version: str) -> str:
    raw = "|".join([str(fixture_id or ""), market, prediction, model_version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _league_name(loaded_model, row: FeatureRow, league_slug: str) -> str:
    return row.league_name or loaded_model.config.get("league_name") or loaded_model.meta.get("display_name") or league_slug


def predict_feature_rows(
    league_slug: str,
    rows: list[FeatureRow],
    generation_run_id: str | None = None,
) -> list[PredictionCandidate]:
    loaded_model = model_registry.get(league_slug)
    config = loaded_model.config
    model_version = loaded_model.model_version
    canonical_slug = loaded_model.league_slug
    output: list[PredictionCandidate] = []

    for row in rows:
        features = row.features or {}
        quality = _feature_quality(row)
        mode = choose_model_mode(loaded_model, features)
        bundle = loaded_model.mode_bundle(mode)
        models = bundle["models"]
        frame = loaded_model.prepare_frame([features], mode=mode)
        timing_goal, timing_winner = _timing_estimates(models, frame, features)

        over15 = sf(pred_bin(models.get("over15"), frame)[0], 0.5)
        under15 = sf(pred_bin(models.get("under15_risk"), frame)[0], 1 - over15)
        over25 = sf(pred_bin(models.get("over25"), frame)[0], 0.5)
        under25 = sf(pred_bin(models.get("under25_risk"), frame)[0], 1 - over25)
        btts = sf(pred_bin(models.get("btts"), frame)[0], 0.5)
        draw_support = sf(pred_bin(models.get("draw_risk"), frame)[0], 0.25)
        favorite_win = sf(pred_bin(models.get("favorite_win"), frame)[0], 0.5)
        favorite_avoid = sf(pred_bin(models.get("favorite_avoid_defeat"), frame)[0], 0.75)
        classes, outcome_proba = pred_outcome(models.get("outcome"), frame)
        class_probabilities = {classes[index]: sf(outcome_proba[0, index], 0) for index in range(len(classes))}
        home_probability = class_probabilities.get("HOME_WIN", 0)
        draw_probability = class_probabilities.get("DRAW", 0)
        away_probability = class_probabilities.get("AWAY_WIN", 0)
        total = home_probability + draw_probability + away_probability
        if total > 0:
            home_probability /= total
            draw_probability /= total
            away_probability /= total

        combined_draw_risk = max(draw_probability, draw_support)
        agreement = sf(features.get("outcome_agreement_proxy", features.get("agreement_score", 65 + abs(home_probability - away_probability) * 35)), 65)
        league_name = _league_name(loaded_model, row, canonical_slug)
        favorite_side = _odds_favorite(features)
        kickoff_time = row.kickoff_time or row.match_date

        base = {
            "generation_run_id": generation_run_id,
            "match_external_id": row.match_external_id,
            "league_slug": canonical_slug,
            "league_name": league_name,
            "match_date": row.match_date,
            "kickoff_time": kickoff_time,
            "home_team": row.home_team,
            "away_team": row.away_team,
            "model_version": model_version,
            "model_mode": mode,
            "feature_quality": quality,
            "api_version": "v1",
            "prediction_contract_version": settings.prediction_contract_version,
            "feature_contract_version": settings.feature_contract_version,
            "candidate_rule_version": settings.candidate_rule_version,
        }

        def append_candidate(
            market: str,
            prediction: str,
            probability: float,
            confidence: float,
            risk: float,
            analysis: str,
            risk_summary: str,
            extras: dict[str, Any],
            rule_note: str = "",
        ) -> None:
            candidate_data = {
                "confidence_score": confidence,
                "risk_score": risk,
                "prediction": prediction,
                **extras,
            }
            eligible, evidence, failure = evaluate_eligibility(market, candidate_data, config, quality)
            tier = tier_for(market, confidence, config)
            factors = _top_factors(loaded_model, market, features, int((config.get("explainability") or {}).get("top_factors_count", 6) or 6))
            codes = _reason_codes(market, confidence, extras, eligible)
            output.append(
                PredictionCandidate(
                    **base,
                    prediction_key=_prediction_key(row.match_external_id, market, prediction, model_version),
                    market=market,
                    prediction=prediction,
                    probability=round(probability, 6),
                    confidence_score=round(confidence, 6),
                    data_quality_score=round(quality.coverage_ratio * 100, 6),
                    risk_score=round(risk, 6),
                    draw_risk_score=extras.get("draw_risk_score"),
                    agreement_score=extras.get("agreement_score"),
                    favorite_win_prob=extras.get("favorite_win_prob"),
                    favorite_avoid_prob=extras.get("favorite_avoid_prob"),
                    under15_risk_prob=extras.get("under15_risk_prob"),
                    under25_risk_prob=extras.get("under25_risk_prob"),
                    draw_risk_prob=extras.get("draw_risk_prob"),
                    ticket_eligible=eligible,
                    tier=tier if eligible else ("review" if market in REVIEW_ONLY_MARKETS else "hidden"),
                    access_level=tier if eligible else None,
                    analysis_summary=analysis,
                    risk_summary=risk_summary,
                    explanation=_explanation(market, prediction, eligible, factors),
                    reason_codes=codes,
                    top_factors=factors,
                    goal_timing_estimate=timing_goal,
                    winner_decision_estimate=timing_winner,
                    eligibility=evidence,
                    rule_note=rule_note or failure,
                )
            )

        over15_confidence, over15_risk, over15_note = score_over15(over15, under15, features)
        append_candidate(
            "over_1_5",
            "YES",
            over15,
            over15_confidence,
            over15_risk,
            "Over 1.5 is assessed from goal-pressure probability and the Under 1.5 risk model.",
            "Risk increases when the Under 1.5 model or a controlled low-tempo profile is strong.",
            {"under15_risk_prob": round(under15, 6)},
            over15_note,
        )

        over25_confidence, over25_risk = score_over25(over25, under25, features)
        append_candidate(
            "over_2_5",
            "YES",
            over25,
            over25_confidence,
            over25_risk,
            "Over 2.5 is generated for review from the goals model and Under 2.5 risk model.",
            "Over 2.5 remains review-only and is not published into tickets.",
            {"under25_risk_prob": round(under25, 6)},
        )

        btts_prediction = "YES" if btts >= 0.5 else "NO"
        btts_confidence = round(max(0, min((0.72 * btts + 0.28 * 0.5) * 100, 100)), 6)
        append_candidate(
            "btts",
            btts_prediction,
            btts,
            btts_confidence,
            100 - btts_confidence,
            "BTTS is generated as a review signal from both-teams-scoring indicators.",
            "BTTS remains review-only and is not published into tickets.",
            {},
        )

        outcome_probabilities = {"HOME_WIN": home_probability, "DRAW": draw_probability, "AWAY_WIN": away_probability}
        top_outcome = max(outcome_probabilities, key=outcome_probabilities.get)
        top_probability = outcome_probabilities[top_outcome]
        outcome_prediction = {"HOME_WIN": "HOME", "AWAY_WIN": "AWAY", "DRAW": "DRAW"}[top_outcome]
        outcome_confidence, outcome_risk = score_outcome(top_probability, combined_draw_risk, favorite_win, favorite_avoid, agreement)
        append_candidate(
            "match_outcome",
            outcome_prediction,
            top_probability,
            outcome_confidence,
            outcome_risk,
            "Match Outcome is assessed with the outcome distribution, favorite support, avoid-defeat support, draw risk, and market agreement.",
            "Match Outcome is published only when every strict candidature gate passes.",
            {
                "draw_risk_score": round(combined_draw_risk * 100, 6),
                "draw_risk_prob": round(draw_support, 6),
                "agreement_score": round(agreement, 6),
                "favorite_win_prob": round(favorite_win, 6),
                "favorite_avoid_prob": round(favorite_avoid, 6),
                "favorite_side": favorite_side,
            },
        )

        if favorite_side == "HOME":
            double_chance_prediction = "1X"
        elif favorite_side == "AWAY":
            double_chance_prediction = "X2"
        else:
            double_chance_prediction = "1X" if home_probability >= away_probability else "X2"
        double_chance_probability = home_probability + draw_probability if double_chance_prediction == "1X" else away_probability + draw_probability
        dc_confidence, dc_risk = score_double_chance(double_chance_probability, combined_draw_risk * 100, favorite_avoid, agreement)
        append_candidate(
            "double_chance",
            double_chance_prediction,
            double_chance_probability,
            dc_confidence,
            dc_risk,
            "Double Chance is assessed from the outcome distribution, draw-risk control, and avoid-defeat support.",
            "Risk increases when draw control, avoid-defeat support, or model agreement weakens.",
            {
                "draw_risk_score": round(combined_draw_risk * 100, 6),
                "draw_risk_prob": round(draw_support, 6),
                "agreement_score": round(agreement, 6),
                "favorite_win_prob": round(favorite_win, 6),
                "favorite_avoid_prob": round(favorite_avoid, 6),
                "favorite_side": favorite_side,
            },
        )

    return output
