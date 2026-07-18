import json
import requests

BASE_URL = "http://127.0.0.1:8000"
HEADERS = {"X-API-Key": "change-me"}


def show(label, response):
    print(label, response.status_code)
    try:
        print(json.dumps(response.json(), indent=2)[:8000])
    except Exception:
        print(response.text[:8000])


payload = {"date": None, "force_refresh": False, "mode": "public"}

show("/sync/league/epl", requests.post(f"{BASE_URL}/sync/league/epl", json=payload, headers=HEADERS))
show("/fixtures/epl", requests.get(f"{BASE_URL}/fixtures/epl", headers=HEADERS))
show("/completed/epl?limit=5", requests.get(f"{BASE_URL}/completed/epl?limit=5", headers=HEADERS))
show("/build-features/epl", requests.post(f"{BASE_URL}/build-features/epl", json=payload, headers=HEADERS))
show("/predict/league/epl", requests.post(f"{BASE_URL}/predict/league/epl", json=payload, headers=HEADERS))
