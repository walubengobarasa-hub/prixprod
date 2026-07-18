import json
from typing import Any

from app.config import model_root_path


class LeagueRegistry:
    def __init__(self):
        self.path = model_root_path() / "leagues.json"
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"leagues": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "leagues" in data:
            return data
        if isinstance(data, dict):
            return {"leagues": data}
        raise ValueError("models/leagues.json must contain an object of league entries.")

    def reload(self) -> dict[str, Any]:
        self._data = self._load()
        return self._data

    def list_leagues(self) -> dict[str, dict[str, Any]]:
        leagues = self._data.get("leagues", {})
        return leagues if isinstance(leagues, dict) else {}

    def get(self, league_slug: str) -> dict[str, Any]:
        leagues = self.list_leagues()
        if league_slug not in leagues:
            raise KeyError(f"League '{league_slug}' is not registered.")
        meta = dict(leagues[league_slug] or {})
        meta.setdefault("slug", league_slug)
        return meta

    def enabled_slugs(self, include_aliases: bool = False) -> list[str]:
        out: list[str] = []
        for slug, meta in self.list_leagues().items():
            if not bool((meta or {}).get("enabled", True)):
                continue
            if not include_aliases and (meta or {}).get("alias_for"):
                continue
            out.append(slug)
        return sorted(out)

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen_seasons: dict[str, str] = {}
        for slug, meta in self.list_leagues().items():
            meta = meta or {}
            if meta.get("alias_for"):
                if meta["alias_for"] not in self.list_leagues():
                    errors.append(f"{slug}: alias_for points to missing league {meta['alias_for']}")
                continue
            folder = model_root_path() / str(meta.get("model_folder", slug))
            if not folder.exists():
                errors.append(f"{slug}: model folder not found: {folder}")
            season_id = meta.get("footystats_season_id") or meta.get("footystats_league_id")
            if not season_id:
                errors.append(f"{slug}: missing FootyStats season/league ID")
            else:
                key = str(season_id)
                if key in seen_seasons and seen_seasons[key] != slug:
                    errors.append(f"{slug}: FootyStats ID {key} duplicates {seen_seasons[key]}")
                seen_seasons[key] = slug
        return errors


league_registry = LeagueRegistry()
