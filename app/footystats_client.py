from typing import Any

import requests

from app.config import settings
from app.storage import read_cache, write_cache


class FootyStatsClient:
    def __init__(self):
        self.base_url = settings.footystats_base_url.rstrip("/")
        self.api_key = settings.footystats_api_key

    def _get(self, endpoint: str, params: dict[str, Any], cache_key: str | None = None, force_refresh: bool = False):
        if cache_key and not force_refresh:
            cached = read_cache(cache_key, max_age_seconds=settings.cache_ttl_seconds)
            if cached is not None:
                self._validate_payload(cached, endpoint)
                return cached
        if not self.api_key:
            raise RuntimeError("FOOTYSTATS_API_KEY is not set.")
        request_params = dict(params)
        request_params["key"] = self.api_key
        response = requests.get(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            params=request_params,
            timeout=settings.footystats_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        self._validate_payload(payload, endpoint)
        if cache_key:
            write_cache(cache_key, payload, metadata={"endpoint": endpoint, "params": params})
        return payload

    @staticmethod
    def _validate_payload(payload: Any, endpoint: str) -> None:
        if not isinstance(payload, dict):
            return
        explicitly_failed = payload.get('success') in (False, 0, '0', 'false')
        explicitly_failed = explicitly_failed or payload.get('status') in ('error', 'failed')
        # FootyStats may return status 200 with an error object instead of match data.
        error = payload.get('error') or payload.get('errors')
        data = payload.get('data', payload.get('matches'))
        if explicitly_failed or error:
            message = payload.get('message') or error or 'provider rejected request'
            raise RuntimeError(f'FootyStats {endpoint} API error: {str(message)[:260]}')

    @staticmethod
    def _data(payload):
        if isinstance(payload, dict):
            return payload.get("data", payload.get("matches", payload))
        return payload

    def league_matches(self, season_or_league_id: int | str, force_refresh: bool = False):
        identifier = str(season_or_league_id)
        payload = self._get(
            "league-matches",
            {"league_id": identifier},
            cache_key=f"footystats_league_matches_{identifier}",
            force_refresh=force_refresh,
        )
        data = self._data(payload)
        if not isinstance(data, list):
            raise RuntimeError(f'FootyStats league-matches returned {type(data).__name__}, not a match list (season {identifier})')
        return data

    def league_table(self, season_id: int | str, max_time=None, force_refresh: bool = False):
        params: dict[str, Any] = {"season_id": season_id}
        if max_time:
            params["max_time"] = int(max_time)
        return self._data(
            self._get(
                "league-tables",
                params,
                cache_key=f"footystats_league_table_{season_id}_{max_time or 'latest'}",
                force_refresh=force_refresh,
            )
        )


footystats_client = FootyStatsClient()
