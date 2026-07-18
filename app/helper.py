import pandas as pd
import json
import requests

df = pd.read_csv("../models/epl/epl_engineered_features.csv")

with open("../models/epl/feature_columns.json", "r") as f:
    feature_columns = json.load(f)["columns"]

row = df.iloc[-1]

features = {}
for col in feature_columns:
    features[col] = float(row[col]) if col in df.columns and pd.notna(row[col]) else 0.0

payload = {
    "league_slug": "epl",
    "rows": [
        {
            "match_external_id": str(row.get("match_external_id", "test_row_001")),
            "match_date": str(row.get("Date", "2026-05-25")),
            "home_team": str(row.get("HomeTeam", "Home Team")),
            "away_team": str(row.get("AwayTeam", "Away Team")),
            "features": features
        }
    ]
}

response = requests.post(
    "http://127.0.0.1:8000/predict/features",
    json=payload
)

print(response.status_code)
print(json.dumps(response.json(), indent=2))