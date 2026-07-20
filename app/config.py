from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PrixPredictor Model API"
    app_env: str = "local"
    app_debug: bool = True
    prix_model_api_key: str = Field(
        default="change-me",
        validation_alias=AliasChoices("PRIX_MODEL_API_KEY", "PREDICTOR_API_KEY"),
    )
    footystats_api_key: str = ""
    footystats_base_url: str = "https://api.football-data-api.com"
    model_root: str = "models"
    cache_root: str = "data/cache"
    cache_ttl_seconds: int = 3600
    footystats_timeout_seconds: int = 45
    minimum_feature_coverage: float = 0.15
    minimum_team_history: int = 3
    maximum_season_staleness_days: int = 370
    max_cached_league_models: int = Field(default=3, validation_alias=AliasChoices("PRIX_MAX_CACHED_LEAGUE_MODELS", "MAX_CACHED_LEAGUE_MODELS"))
    feature_contract_version: str = "v0.6.4"
    prediction_contract_version: str = "v0.6.4"
    candidate_rule_version: str = "2026-07-18"
    platform_timezone: str = "Africa/Nairobi"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def model_root_path() -> Path:
    return (project_root() / settings.model_root).resolve()


def cache_root_path() -> Path:
    path = (project_root() / settings.cache_root).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
