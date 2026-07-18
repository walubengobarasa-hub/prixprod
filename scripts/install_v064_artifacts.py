#!/usr/bin/env python3
"""Install PrixPredictor v0.6.4 league artifact folders into this FastAPI build.

Usage:
  python scripts/install_v064_artifacts.py /path/to/model_outputs/v064

The source may contain folders such as spain/, italy/, finland/, allsvenskan/.
Each folder must contain model_config.json.
"""
from pathlib import Path
import json, shutil, sys

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'models'
REGISTRY = MODELS / 'leagues.json'

def main(src: str) -> None:
    source = Path(src)
    if not source.exists():
        raise SystemExit(f'Source not found: {source}')
    registry = json.loads(REGISTRY.read_text(encoding='utf-8')) if REGISTRY.exists() else {'leagues': {}}
    leagues = registry.setdefault('leagues', {})
    installed = []
    for folder in sorted([p for p in source.iterdir() if p.is_dir()]):
        cfg_path = folder / 'model_config.json'
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        slug = cfg.get('league_slug') or folder.name
        dst = MODELS / slug
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(folder, dst)
        meta = leagues.get(slug, {})
        meta.update({
            'display_name': cfg.get('league_name', slug.replace('_',' ').title()),
            'league_code': slug,
            'model_version': cfg.get('model_version', 'v0.6.4'),
            'enabled': True,
            'competition_type': 'league',
            'model_family': cfg.get('model_family', 'main_league'),
            'model_folder': slug,
            'footystats_league_id': meta.get('footystats_league_id'),
            'footystats_season_id': meta.get('footystats_season_id'),
        })
        leagues[slug] = meta
        installed.append(slug)
    REGISTRY.write_text(json.dumps(registry, indent=2), encoding='utf-8')
    print('Installed:', ', '.join(installed) if installed else 'none')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python scripts/install_v064_artifacts.py /path/to/model_outputs/v064')
    main(sys.argv[1])
