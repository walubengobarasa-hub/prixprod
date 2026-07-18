from typing import Any, Literal

from pydantic import BaseModel, Field

Market = Literal["double_chance", "over_1_5", "over_2_5", "match_outcome", "btts"]
Tier = Literal["review", "public", "premium", "elite", "hidden"]
TicketScope = Literal["league_specific", "cross_league", "single_match_insights"]


class FeatureQuality(BaseModel):
    expected_features: int = 0
    non_zero_features: int = 0
    coverage_ratio: float = 0.0
    critical_features_missing: list[str] = Field(default_factory=list)
    home_prior_matches: int = 0
    away_prior_matches: int = 0
    min_team_matches_before: int = 0
    odds_available: bool = False
    pre_match_fields_available: int = 0
    leakage_safe: bool = True
    passed: bool = False


class FeatureRow(BaseModel):
    match_external_id: str | None = None
    match_date: str
    home_team: str
    away_team: str
    league_slug: str | None = None
    league_name: str | None = None
    kickoff_time: str | None = None
    features: dict[str, Any] = Field(default_factory=dict)
    feature_meta: dict[str, Any] = Field(default_factory=dict)


class FeaturePredictionRequest(BaseModel):
    league_slug: str = "epl"
    date: str | None = None
    mode: Literal["review", "public", "premium", "elite"] = "public"
    rows: list[FeatureRow]


class LeagueDatePredictionRequest(BaseModel):
    date: str | None = None
    mode: Literal["review", "public", "premium", "elite"] = "public"
    force_refresh: bool = False


class EligiblePredictionRequest(BaseModel):
    leagues: list[str] = Field(default_factory=list)
    date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    force_refresh: bool = False
    include_ineligible: bool = False


class MockFixturePredictionRequest(BaseModel):
    match_external_id: str | None = None
    match_date: str
    kickoff_time: str | None = None
    home_team: str
    away_team: str
    mode: Literal["review", "public", "premium", "elite"] = "public"
    odds_ft_1: float | None = None
    odds_ft_x: float | None = None
    odds_ft_2: float | None = None
    odds_ft_over15: float | None = None
    odds_ft_under15: float | None = None
    odds_ft_over25: float | None = None
    odds_ft_under25: float | None = None
    odds_btts_yes: float | None = None
    odds_btts_no: float | None = None
    odds_doublechance_1x: float | None = None
    odds_doublechance_12: float | None = None
    odds_doublechance_x2: float | None = None


class PredictionFactor(BaseModel):
    feature: str
    label: str | None = None
    value: float | str | None = None
    importance: float | None = None
    direction: str | None = None
    impact: str | None = None


class TimingEstimate(BaseModel):
    first_goal_window: str | None = None
    likely_decision_window: str | None = None
    confidence: str | None = None
    profile_score: float | None = None
    reason: str | None = None


class EligibilityEvidence(BaseModel):
    passed: bool = False
    rule_version: str | None = None
    checks: dict[str, bool] = Field(default_factory=dict)
    failed_reasons: list[str] = Field(default_factory=list)


class PredictionCandidate(BaseModel):
    prediction_key: str
    generation_run_id: str | None = None
    match_external_id: str | None = None
    league_slug: str
    league_name: str | None = None
    match_date: str
    kickoff_time: str | None = None
    home_team: str
    away_team: str
    market: Market
    prediction: str
    probability: float
    confidence_score: float
    data_quality_score: float = 0.0
    risk_score: float | None = None
    draw_risk_score: float | None = None
    agreement_score: float | None = None
    favorite_win_prob: float | None = None
    favorite_avoid_prob: float | None = None
    under15_risk_prob: float | None = None
    under25_risk_prob: float | None = None
    draw_risk_prob: float | None = None
    ticket_eligible: bool = False
    tier: Tier = "hidden"
    model_version: str
    model_mode: str | None = None
    access_level: str | None = None
    analysis_summary: str
    risk_summary: str
    explanation: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    top_factors: list[PredictionFactor] = Field(default_factory=list)
    goal_timing_estimate: TimingEstimate | None = None
    winner_decision_estimate: TimingEstimate | None = None
    feature_quality: FeatureQuality | None = None
    eligibility: EligibilityEvidence | None = None
    rule_note: str | None = None
    api_version: str = "v1"
    prediction_contract_version: str = "v0.6.4"
    feature_contract_version: str = "v0.6.4"
    candidate_rule_version: str = "2026-07-18"


class TicketItem(BaseModel):
    match_external_id: str | None = None
    match_date: str
    kickoff_time: str | None = None
    home_team: str
    away_team: str
    league_slug: str
    league_name: str | None = None
    market: Market
    prediction: str
    confidence_score: float
    data_quality_score: float = 0.0
    risk_score: float | None = None
    model_version: str | None = None
    model_mode: str | None = None
    explanation: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    top_factors: list[PredictionFactor] = Field(default_factory=list)
    goal_timing_estimate: TimingEstimate | None = None
    winner_decision_estimate: TimingEstimate | None = None
    rule_note: str | None = None


class IncludedLeague(BaseModel):
    league_slug: str
    league_name: str | None = None


class TicketRecommendation(BaseModel):
    ticket_type: str
    title: str
    league_slug: str
    league_name: str | None = None
    date: str
    tier: Literal["free", "premium", "elite"]
    access_level: Literal["free", "premium", "elite"] | None = None
    ticket_scope: TicketScope = "league_specific"
    ticket_packaging_mode: str | None = None
    primary_league_slug: str | None = None
    primary_league_name: str | None = None
    included_leagues: list[IncludedLeague] = Field(default_factory=list)
    items: list[TicketItem]
    avg_confidence: float
    avg_risk: float | None = None


class PredictionResponse(BaseModel):
    league_slug: str
    model_version: str
    date: str | None = None
    candidates: list[PredictionCandidate]
    tickets: list[TicketRecommendation] = Field(default_factory=list)
    single_match_insights: list[PredictionCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    api_version: str = "v1"
    prediction_contract_version: str = "v0.6.4"
    feature_contract_version: str = "v0.6.4"
    candidate_rule_version: str = "2026-07-18"


class LeaguePredictionSummary(BaseModel):
    league_slug: str
    league_name: str | None = None
    footystats_identifier: str | None = None
    status: str
    latest_data_match_date: str | None = None
    latest_completed_date: str | None = None
    fixtures_found: int = 0
    feature_rows: int = 0
    candidates_generated: int = 0
    eligible_candidates: int = 0
    average_feature_coverage: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class EligiblePredictionResponse(BaseModel):
    api_version: str = "v1"
    prediction_contract_version: str = "v0.6.4"
    feature_contract_version: str = "v0.6.4"
    candidate_rule_version: str = "2026-07-18"
    generation_run_id: str
    generated_at: str
    date_from: str
    date_to: str
    requested_leagues: list[str]
    eligible_candidates: list[PredictionCandidate]
    reviewed_candidates: list[PredictionCandidate] = Field(default_factory=list)
    league_summaries: list[LeaguePredictionSummary]
    warnings: list[str] = Field(default_factory=list)
