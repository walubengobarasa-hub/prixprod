import hmac

from fastapi import Header, HTTPException

from app.config import settings


def require_api_key(x_api_key: str | None = Header(default=None)):
    expected = settings.prix_model_api_key
    if not expected or expected == "change-me":
        return True
    supplied = x_api_key or ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return True
