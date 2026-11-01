import json
import os
import tempfile
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
    # json.dumps() constructs another full-sized copy in RAM. Stream directly
    # to a unique temp file and atomically swap it into place on success.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp",
                                         delete=False) as temporary:
            temp_path = temporary.name
            json.dump(wrapper, temporary, separators=(",", ":"), default=str, ensure_ascii=False)
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
    return path


def read_cache(name: str, max_age_seconds: int | None = None):
    path = cache_path(name)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as source:
            wrapper = json.load(source)
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
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError):
        return None
