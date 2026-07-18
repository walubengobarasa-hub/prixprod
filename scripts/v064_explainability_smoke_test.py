#!/usr/bin/env python3
"""Local smoke test for v0.6.4 explainable models.
Run from project root after installing dependencies:
  python scripts/v064_explainability_smoke_test.py allsvenskan
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.model_registry import model_registry
from app.predictor import predict_feature_rows
from app.schemas import FeatureRow

league = sys.argv[1] if len(sys.argv) > 1 else 'allsvenskan'
lm = model_registry.get(league)
features = {c: 0 for c in (lm.raw_feature_columns or [])}
# Add odds so odds-aware mode is selected where available.
features.update({'odds_ft_1': 1.80, 'odds_ft_x': 3.40, 'odds_ft_2': 4.20, 'odds_ft_over15': 1.35, 'odds_ft_under15': 3.05, 'odds_ft_over25': 1.95, 'odds_ft_under25': 1.85})
row = FeatureRow(match_external_id='smoke-1', match_date='2026-07-16', kickoff_time='2026-07-16T19:00:00', home_team='Home FC', away_team='Away FC', league_slug=league, features=features)
cands = predict_feature_rows(league, [row])
print(json.dumps({
    'league': league,
    'model_version': lm.model_version,
    'candidate_count': len(cands),
    'markets': [c.market for c in cands],
    'sample': cands[0].model_dump() if cands else None,
}, indent=2, default=str))
