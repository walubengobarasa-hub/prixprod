import json
import requests

BASE_URL = "http://127.0.0.1:8000"
HEADERS = {"X-API-Key": "change-me"}


def show(label, response):
    print(label, response.status_code)
    try:
        print(json.dumps(response.json(), indent=2)[:10000])
    except Exception:
        print(response.text[:10000])

# First make sure completed-match history is cached. With the FootyStats test
# key this usually loads the 2018/19 EPL season.
show("/sync/league/epl", requests.post(f"{BASE_URL}/sync/league/epl", json={"force_refresh": False}, headers=HEADERS))

# Use teams from the cached historical season and a future date after the season
# so the feature builder has prior matches to calculate rolling features.
payload = {
    "match_external_id": "mock_liverpool_wolves_20190519",
    "match_date": "2019-05-19",
    "home_team": "Liverpool",
    "away_team": "Wolverhampton Wanderers",
    "odds_ft_1": 1.32,
    "odds_ft_x": 5.80,
    "odds_ft_2": 9.00,
    "odds_ft_over15": 1.18,
    "odds_ft_under15": 4.95,
    "odds_ft_over25": 1.57,
    "odds_ft_under25": 2.40,
    "odds_btts_yes": 1.95,
    "odds_btts_no": 1.83,
    "odds_doublechance_1x": 1.04,
    "odds_doublechance_12": 1.11,
    "odds_doublechance_x2": 3.60
}

show("/predict/mock-fixture/epl", requests.post(f"{BASE_URL}/predict/mock-fixture/epl", json=payload, headers=HEADERS))
