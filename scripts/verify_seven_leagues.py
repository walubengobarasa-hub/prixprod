#!/usr/bin/env python3
"""Read-only pre-deployment audit for the seven extra Prix competitions.

Run from the FastAPI project root with the same env as the service:
    python scripts/verify_seven_leagues.py
    python scripts/verify_seven_leagues.py --load

--load may briefly consume memory to deserialize each model sequentially.
No network, model files or registry entries are modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED = {
    "denmark-1st-division": "league_v064",
    "england-efl-trophy": "domestic_cup_v1",
    "europe-uefa-women-s-champions-league": "continental_cup_v1",
    "international-africa-cup-of-nations-qualification": "international_competition_v1",
    "international-concacaf-nations-league": "international_competition_v1",
    "international-uefa-nations-league": "international_competition_v1",
    "jamaica-jamaica-national-premier-league": "league_v064",
}


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--load",action="store_true",help="Load/test actual pickle model bundles")
    parser.add_argument("--predict",action="store_true",help="Run synthetic in-memory inference; no FootyStats or published picks")
    args=parser.parse_args()
    import sklearn
    from app.config import model_root_path
    from app.league_registry import league_registry
    root=model_root_path()
    errors=[]
    rows=[]
    for slug, expected_family in EXPECTED.items():
        row={"slug":slug,"enabled":False,"family":None,"version":None,"status":"missing","market_statuses":{}}
        try:
            entry=league_registry.get(slug)
            folder=root/str(entry.get('model_folder') or slug)
            row['enabled']=entry.get('enabled') is True
            if not row['enabled']:
                errors.append(f'{slug}: registry entry not enabled')
            season=entry.get('footystats_season_id') or entry.get('footystats_league_id')
            row['season_id']=season
            if not season: errors.append(f'{slug}: FootyStats season ID missing')
            config=json.loads((folder/'model_config.json').read_text(encoding='utf-8'))
            meta=json.loads((folder/'model_metadata_v064.json').read_text(encoding='utf-8'))
            row['family']=config.get('model_family')
            row['version']=config.get('model_version')
            row['status']=meta.get('deployment_status','unknown')
            row['market_statuses']={k:v.get('status') for k,v in (config.get('market_rules') or {}).items() if k in ('double_chance','over_1_5','match_outcome')}
            row['sklearn_trained']=meta.get('sklearn_training_version')
            row['sklearn_runtime']=sklearn.__version__
            if config.get('league_slug')!=slug:
                errors.append(f'{slug}: model_config slug mismatch')
            if entry.get('model_family')!=expected_family or row['family']!=expected_family:
                errors.append(f'{slug}: unexpected model family (registry={entry.get("model_family")}, artifact={row["family"]})')
            if meta.get('sklearn_training_version') and meta['sklearn_training_version'].split('.')[:2]!=sklearn.__version__.split('.')[:2]:
                errors.append(f'{slug}: sklearn trained={meta["sklearn_training_version"]}, serving={sklearn.__version__}; retrain or verify exact compatible runtime')
            if args.load or args.predict:
                from app.model_registry import model_registry
                m=model_registry.get(slug)
                row['loaded_models']=sum(obj is not None for obj in m.models.values())
                row['feature_columns']=len(m.raw_feature_columns)
                if row['loaded_models']!=11 or row['feature_columns']!=400:
                    errors.append(f'{slug}: expected 11 models and 400 features, got {row["loaded_models"]} and {row["feature_columns"]}')
                if args.predict:
                    from app.predictor import predict_feature_rows, _market_status
                    from app.schemas import FeatureRow
                    # This is a DESERIALIZATION & PREDICTION smoke check only.
                    # Feature values are synthetic and may never be published.
                    features = {col: 0.35 for col in m.raw_feature_columns}
                    test_row = FeatureRow(
                        match_external_id="test-only-0001", match_date="2026-11-30",
                        home_team="Synthetic Home", away_team="Synthetic Away",
                        league_slug=slug, features=features,
                        feature_meta={"expected_features": len(features),
                                      "non_zero_features": len(features), "coverage_ratio": 1.0,
                                      "home_prior_matches": 10, "away_prior_matches": 10,
                                      "leakage_safe": True, "passed": True},
                    )
                    predictions = predict_feature_rows(slug, [test_row], generation_run_id="offline-test")
                    row['synthetic_candidates'] = len(predictions)
                    row['synthetic_markets'] = sorted({c.market for c in predictions})
                    row['synthetic_eligible'] = sum(bool(c.ticket_eligible) for c in predictions)
                    if not predictions:
                        errors.append(f'{slug}: no prediction candidates generated')
                    if any(c.ticket_eligible and _market_status(m.config, c.market) == "review_only" for c in predictions):
                        errors.append(f'{slug}: review-only market improperly eligible')
            if not row['enabled']:
                row['status']='disabled'
        except Exception as exc:
            errors.append(f'{slug}: {exc.__class__.__name__}: {exc}')
            row['status']='error'
        rows.append(row)
    result={"ok":not errors,"model_root":str(root),"sklearn_runtime":sklearn.__version__,"leagues":rows,"errors":errors,
            "note":"Synthetic predictions test inference plumbing only; no live feature/provider validation. Registry enabled does not override review_only."}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if not errors else 1


if __name__=='__main__':
    raise SystemExit(main())
