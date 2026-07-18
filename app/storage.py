import json
import os
from datetime import datetime, timezone
from typing import Any

from app.config import cache_root_path


def cache_path(name: str):
    return cache_root_path() / f"{name.replace('/', '_').replace(':', '_')}.json"


def write_cache(name: str, payload: Any, metadata: dict[str, Any] | None = None):
    path = cache_path(name)
    wrapper = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
        "payload": payload,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(wrapper, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)
    return path


def read_cache(name: str, max_age_seconds: int | None = None):
    path = cache_path(name)
    if not path.exists():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if max_age_seconds is not None:
        cached_at = wrapper.get("cached_at")
        try:
            cached_dt = datetime.fromisoformat(str(cached_at).replace("Z", "+00:00"))
            if cached_dt.tzinfo is None:
                cached_dt = cached_dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - cached_dt).total_seconds()
            if age > max_age_seconds:
                return None
        except Exception:
            return None
    return wrapper.get("payload")


def read_cache_wrapper(name: str) -> dict[str, Any] | None:
    path = cache_path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
