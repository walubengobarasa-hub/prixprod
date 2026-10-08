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
    model_release_root: str = "data/model_releases"
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


def _resolve_configured_path(raw: str) -> Path:
    value = Path(str(raw).strip())
    return value.resolve() if value.is_absolute() else (project_root() / value).resolve()


def _ensure_writable_directory(requested: Path, fallback: Path) -> tuple[Path, bool, str | None]:
    """Return a writable directory without crashing application startup.

    The configured path is always preferred. If the runtime cannot create/write it
    (for example /var/data when no Render disk is mounted), use the fallback path.
    The boolean indicates whether the requested path is active.
    """
    try:
        requested.mkdir(parents=True, exist_ok=True)
        probe = requested / ".prix_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return requested, True, None
    except OSError as exc:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback.resolve(), False, f"{exc.__class__.__name__}: {exc}"


# Resolve once so every registry/model component uses the same effective root.
_REQUESTED_MODEL_ROOT = _resolve_configured_path(settings.model_root)
_MODEL_ROOT, MODEL_ROOT_PERSISTENT, MODEL_ROOT_FALLBACK_REASON = _ensure_writable_directory(
    _REQUESTED_MODEL_ROOT,
    project_root() / "models",
)


def _bootstrap_model_root_from_bundle(active_root: Path) -> dict:
    """Seed a newly mounted persistent model root from the bundled application models.

    Render persistent disks start empty. When MODEL_ROOT points at a fresh disk, the
    application must retain the production registry/model folders shipped with the
    deployment instead of starting with an empty registry. Existing persistent files
    are never overwritten here.
    """
    bundled = (project_root() / "models").resolve()
    active = active_root.resolve()
    result = {"bootstrapped": False, "copied": [], "source": str(bundled)}
    if active == bundled or not bundled.is_dir():
        return result
    try:
        active.mkdir(parents=True, exist_ok=True)
        registry = active / "leagues.json"
        bundled_registry = bundled / "leagues.json"
        # A fresh disk has no registry. Seed the registry plus every bundled model
        # directory. If a directory already exists, leave it untouched.
        if not registry.exists() and bundled_registry.is_file():
            import shutil
            shutil.copy2(bundled_registry, registry)
            result["copied"].append("leagues.json")
            for child in bundled.iterdir():
                if not child.is_dir():
                    continue
                target = active / child.name
                if target.exists():
                    continue
                shutil.copytree(child, target)
                result["copied"].append(child.name)
            result["bootstrapped"] = True
    except OSError as exc:
        result["error"] = f"{exc.__class__.__name__}: {exc}"
    return result


MODEL_ROOT_BOOTSTRAP = _bootstrap_model_root_from_bundle(_MODEL_ROOT)

_REQUESTED_RELEASE_ROOT = _resolve_configured_path(settings.model_release_root)
_RELEASE_ROOT, RELEASE_ROOT_PERSISTENT, RELEASE_ROOT_FALLBACK_REASON = _ensure_writable_directory(
    _REQUESTED_RELEASE_ROOT,
    Path("/tmp/prix-model-releases"),
)


def model_root_path() -> Path:
    return _MODEL_ROOT


def model_release_root_path() -> Path:
    return _RELEASE_ROOT


def storage_status() -> dict:
    return {
        "model_root": str(_MODEL_ROOT),
        "requested_model_root": str(_REQUESTED_MODEL_ROOT),
        "model_root_requested_path_active": MODEL_ROOT_PERSISTENT,
        "model_root_fallback_reason": MODEL_ROOT_FALLBACK_REASON,
        "model_release_root": str(_RELEASE_ROOT),
        "requested_model_release_root": str(_REQUESTED_RELEASE_ROOT),
        "model_release_root_requested_path_active": RELEASE_ROOT_PERSISTENT,
        "model_release_root_fallback_reason": RELEASE_ROOT_FALLBACK_REASON,
        "persistent_storage_ready": MODEL_ROOT_PERSISTENT and RELEASE_ROOT_PERSISTENT,
        "model_root_bootstrap": MODEL_ROOT_BOOTSTRAP,
    }


def cache_root_path() -> Path:
    path = _resolve_configured_path(settings.cache_root)
    path.mkdir(parents=True, exist_ok=True)
    return path
