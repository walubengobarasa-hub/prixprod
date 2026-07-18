from __future__ import annotations

import json
from collections import OrderedDict
from threading import RLock
from typing import Any

import joblib
import pandas as pd

from app.config import model_root_path, settings
from app.league_registry import league_registry


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def normalize_feature_name(name: str) -> str:
    return str(name).replace(">", "_").replace("<", "_")


def _patch_sklearn_pickle_compat(obj: Any) -> Any:
    """Best-effort compatibility for sklearn 1.6.x pickles loaded on newer sklearn.

    Some Colab artifacts include SimpleImputer objects that expect _fill_dtype
    after unpickling. Newer sklearn versions may not restore that private attr,
    causing prediction-time AttributeError.
    """
    try:
        from sklearn.impute import SimpleImputer
    except Exception:
        SimpleImputer = None  # type: ignore

    seen: set[int] = set()

    def walk(o: Any) -> None:
        oid = id(o)
        if oid in seen:
            return
        seen.add(oid)
        if SimpleImputer is not None and isinstance(o, SimpleImputer):
            if not hasattr(o, "_fill_dtype"):
                setattr(o, "_fill_dtype", getattr(o, "_fit_dtype", None))
        for attr in ("steps",):
            steps = getattr(o, attr, None)
            if steps:
                for item in steps:
                    if isinstance(item, tuple) and len(item) == 2:
                        walk(item[1])
        for attr in ("estimator", "base_estimator", "final_estimator", "best_estimator_"):
            child = getattr(o, attr, None)
            if child is not None and child is not o:
                walk(child)
        for attr in ("calibrated_classifiers_", "estimators_", "transformers_"):
            children = getattr(o, attr, None)
            if children:
                for child in children:
                    if isinstance(child, tuple):
                        for part in child:
                            if not isinstance(part, str):
                                walk(part)
                    else:
                        walk(child)
    walk(obj)
    return obj


class LoadedLeagueModel:
    """Loads one league model folder.

    Supports both the original EPL single-mode artifact layout and cup-competition
    multi-mode layouts such as World Cup v0.5 with football_only and odds_aware modes.
    """

    MODEL_ALIASES = {
        "over15_base": "over15",
        "btts_review": "btts",
        "outcome_calibrated": "outcome",
        "favorite_win_support": "favorite_win",
        "favorite_avoid_defeat_support": "favorite_avoid_defeat",
        "over25_base": "over25",
        "over25_base_review": "over25",
        "under25_risk": "under25_risk",
        "draw_risk_support": "draw_risk",
        "over35_review": "over35_review",
        "first_goal_window": "first_goal_window",
        "winner_decision_window": "winner_decision_window",
    }

    def __init__(self, league_slug: str):
        self.league_slug = league_slug
        meta = league_registry.get(league_slug)
        if meta.get("alias_for"):
            meta = league_registry.get(meta["alias_for"])
            self.league_slug = meta.get("slug", meta.get("league_slug", league_slug))
        self.meta = meta
        self.folder = model_root_path() / meta.get("model_folder", league_slug)
        if not self.folder.exists():
            raise FileNotFoundError(f"Model folder not found: {self.folder}")

        self.config = json.loads((self.folder / "model_config.json").read_text(encoding="utf-8"))
        self.model_version = self.config.get("model_version", meta.get("model_version", "unknown"))
        self.explainability_profile = self._load_json_optional("explainability_profile.json")
        self.feature_importances = self._load_feature_importances()
        self.modes: dict[str, dict[str, Any]] = {}

        if isinstance(self.config.get("modes"), dict) and self.config["modes"]:
            for mode_name, mode_cfg in self.config["modes"].items():
                raw_cols = self._load_feature_columns_for(mode_cfg.get("feature_columns_file", "feature_columns.json"))
                models = self._load_models_from_map(mode_cfg.get("models", {}))
                fitted_cols = self._extract_fitted_feature_columns(models, raw_cols)
                self.modes[mode_name] = {"raw_feature_columns": raw_cols, "models": models, "model_feature_columns": fitted_cols}
        else:
            raw_cols = self._load_feature_columns_for(self.config.get("feature_columns_file", "feature_columns.json"))
            models = self._load_models_from_map(self.config.get("models", {}))
            fitted_cols = self._extract_fitted_feature_columns(models, raw_cols)
            single_mode = str(self.config.get("model_mode") or self.meta.get("model_mode") or "standard")
            self.modes[single_mode] = {"raw_feature_columns": raw_cols, "models": models, "model_feature_columns": fitted_cols}

        configured_default = str(self.config.get("default_mode") or self.config.get("model_mode") or "")
        default_mode = configured_default if configured_default in self.modes else ("odds_aware" if "odds_aware" in self.modes else ("standard" if "standard" in self.modes else next(iter(self.modes))))
        self.default_mode = default_mode
        default = self.modes[default_mode]
        self.raw_feature_columns = default["raw_feature_columns"]
        self.models = default["models"]
        self.model_feature_columns = default["model_feature_columns"]
        self.feature_columns = self.raw_feature_columns
        self.fitted_feature_columns = self.model_feature_columns


    def _load_json_optional(self, filename: str) -> dict[str, Any]:
        path = self.folder / filename
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_feature_importances(self) -> dict[str, list[dict[str, Any]]]:
        """Load v0.6.4 feature importance CSVs if present.

        The API uses these only for explanation text. Prediction remains fully
        model-driven.
        """
        out: dict[str, list[dict[str, Any]]] = {}
        try:
            for path in self.folder.glob("*_feature_importance.csv"):
                market = path.name.replace(f"{self.league_slug}_", "").replace("_feature_importance.csv", "")
                market = self.MODEL_ALIASES.get(market, market)
                try:
                    df = pd.read_csv(path)
                    cols = set(df.columns)
                    feature_col = "feature" if "feature" in cols else ("raw_feature" if "raw_feature" in cols else None)
                    if not feature_col or "importance" not in cols:
                        continue
                    rows = []
                    for _, r in df.head(40).iterrows():
                        rows.append({
                            "feature": str(r.get(feature_col, "")),
                            "raw_feature": str(r.get("raw_feature", r.get(feature_col, ""))),
                            "importance": float(r.get("importance", 0) or 0),
                        })
                    out[market] = rows
                except Exception:
                    continue
        except Exception:
            pass
        return out

    def _load_feature_columns_for(self, filename: str) -> list[str]:
        path = self.folder / filename
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            columns = data
        elif isinstance(data, dict):
            columns = (
                data.get("columns")
                or data.get("odds_aware_features")
                or data.get("odds_features")
                or data.get("feature_columns")
                or data.get("football_features")
                or []
            )
        else:
            columns = []
        return [str(c) for c in columns]

    def _load_models_from_map(self, model_map: dict[str, str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for raw_key, filename in model_map.items():
            path = self.folder / filename
            model = _patch_sklearn_pickle_compat(joblib.load(path)) if filename and path.exists() else None
            key = self.MODEL_ALIASES.get(raw_key, raw_key)
            out[key] = model
            out[raw_key] = model
        return out

    def _extract_fitted_feature_columns(self, models: dict[str, Any], raw_feature_columns: list[str]) -> list[str]:
        for model in models.values():
            if model is None:
                continue
            names = getattr(model, "feature_names_in_", None)
            if names is not None and len(names):
                return [str(c) for c in list(names)]
            for attr in ("estimator", "base_estimator", "named_steps"):
                child = getattr(model, attr, None)
                if child is None:
                    continue
                if isinstance(child, dict):
                    for step in child.values():
                        step_names = getattr(step, "feature_names_in_", None)
                        if step_names is not None and len(step_names):
                            return [str(c) for c in list(step_names)]
                else:
                    step_names = getattr(child, "feature_names_in_", None)
                    if step_names is not None and len(step_names):
                        return [str(c) for c in list(step_names)]
        return [normalize_feature_name(c) for c in raw_feature_columns]

    def available_modes(self) -> list[str]:
        return list(self.modes.keys())

    def mode_bundle(self, mode: str | None = None) -> dict[str, Any]:
        selected = mode or self.default_mode
        if selected not in self.modes:
            selected = self.default_mode
        return self.modes[selected]

    def _row_value(self, row: dict[str, Any], raw_col: str, fitted_col: str) -> float:
        if fitted_col in row:
            return _safe_float(row.get(fitted_col))
        if raw_col in row:
            return _safe_float(row.get(raw_col))
        normalized_row = {normalize_feature_name(k): v for k, v in row.items()}
        if fitted_col in normalized_row:
            return _safe_float(normalized_row.get(fitted_col))
        return 0.0

    def prepare_frame(self, rows: list[dict], mode: str | None = None) -> pd.DataFrame:
        bundle = self.mode_bundle(mode)
        fitted_cols = bundle["model_feature_columns"]
        raw_cols = bundle["raw_feature_columns"]
        if not rows:
            return pd.DataFrame(columns=fitted_cols)
        if fitted_cols:
            use_raw_positions = len(raw_cols) == len(fitted_cols)
            matrix: list[list[float]] = []
            for row in rows:
                values = []
                for idx, fitted_col in enumerate(fitted_cols):
                    raw_col = raw_cols[idx] if use_raw_positions else fitted_col
                    values.append(self._row_value(row, raw_col, fitted_col))
                matrix.append(values)
            return pd.DataFrame(matrix, columns=fitted_cols).fillna(0)
        df = pd.DataFrame(rows)
        df.columns = [normalize_feature_name(c) for c in df.columns]
        df = df.select_dtypes(include=["number"]).copy()
        return df.fillna(0)


class ModelRegistry:
    def __init__(self):
        self._cache: OrderedDict[str, LoadedLeagueModel] = OrderedDict()
        self._lock = RLock()

    def get(self, league_slug: str) -> LoadedLeagueModel:
        with self._lock:
            meta = league_registry.get(league_slug)
            cache_key = meta.get("alias_for", league_slug)
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

            self._cache[cache_key] = LoadedLeagueModel(cache_key)
            self._cache.move_to_end(cache_key)
            max_cached = max(1, int(settings.max_cached_league_models or 1))
            while len(self._cache) > max_cached:
                self._cache.popitem(last=False)
            return self._cache[cache_key]

    def reload(self, league_slug: str) -> LoadedLeagueModel:
        with self._lock:
            league_registry.reload()
            meta = league_registry.get(league_slug)
            cache_key = meta.get("alias_for", league_slug)
            self._cache.pop(cache_key, None)
            return self.get(cache_key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def validate_all(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        required_models = [
            "over15", "under15_risk", "btts", "over25", "under25_risk", "outcome",
            "favorite_win", "favorite_avoid_defeat", "draw_risk", "first_goal_window",
            "winner_decision_window",
        ]
        required_files = [
            "model_config.json", "feature_columns.json", "model_metadata_v064.json",
            "explainability_profile.json",
        ]
        for slug in league_registry.enabled_slugs():
            try:
                model = self.get(slug)
                missing_models = [name for name in required_models if model.models.get(name) is None]
                missing_files = [filename for filename in required_files if not (model.folder / filename).exists()]
                feature_count = len(model.raw_feature_columns)
                fitted_feature_count = len(model.model_feature_columns)
                feature_contract_matches = bool(feature_count and fitted_feature_count == feature_count)
                results.append({
                    "league_slug": slug,
                    "ok": not missing_models and not missing_files and feature_contract_matches,
                    "model_version": model.model_version,
                    "model_mode": model.default_mode,
                    "feature_count": feature_count,
                    "fitted_feature_count": fitted_feature_count,
                    "feature_contract_matches": feature_contract_matches,
                    "missing_models": missing_models,
                    "missing_files": missing_files,
                })
            except Exception as exc:
                results.append({"league_slug": slug, "ok": False, "error": str(exc)})
        return results


model_registry = ModelRegistry()
