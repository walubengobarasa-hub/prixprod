from __future__ import annotations
import base64, json, shutil, tempfile, zipfile
from pathlib import Path
from typing import Any
from app.config import model_root_path, model_release_root_path
from app.league_registry import league_registry
from app.model_registry import model_registry

RELEASE_ROOT = model_release_root_path()

def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    for info in zf.infolist():
        name = info.filename.replace('\\','/')
        if name.startswith('/') or '..' in Path(name).parts:
            raise ValueError(f'Unsafe ZIP path: {info.filename}')
    zf.extractall(target)

def _models_dir(extract: Path) -> Path:
    direct = extract / 'models'
    if direct.is_dir(): return direct
    # Colab output ZIP may wrap the output folder.
    for p in extract.rglob('models'):
        if p.is_dir(): return p
    return extract

def deploy_release(release_key: str, archive_base64: str, registry: dict[str, Any]) -> dict[str, Any]:
    if not release_key or not isinstance(registry, dict) or not isinstance(registry.get('leagues'), dict):
        raise ValueError('release_key and a leagues registry are required.')
    rel = RELEASE_ROOT / release_key
    if rel.exists(): shutil.rmtree(rel)
    rel.mkdir(parents=True)
    archive = rel / 'models.zip'
    archive.write_bytes(base64.b64decode(archive_base64.encode('ascii')))
    extract = rel / 'extract'; extract.mkdir()
    with zipfile.ZipFile(archive) as zf: _safe_extract(zf, extract)
    incoming = _models_dir(extract)
    folders = [p for p in incoming.iterdir() if p.is_dir() and (p/'model_config.json').exists()]
    if not folders: raise ValueError('No model folders with model_config.json were found in the release.')
    target = model_root_path(); target.mkdir(parents=True, exist_ok=True)
    backup = rel / 'backup'; backup.mkdir()
    changed=[]
    old_registry = target / 'leagues.json'
    if old_registry.exists(): shutil.copy2(old_registry, backup/'leagues.json')
    try:
        for src in folders:
            dst=target/src.name
            if dst.exists(): shutil.copytree(dst,backup/src.name)
            shutil.rmtree(dst,ignore_errors=True); shutil.copytree(src,dst); changed.append(src.name)
        tmp=target/'leagues.json.tmp'; tmp.write_text(json.dumps(registry,indent=2,ensure_ascii=False)+'\n',encoding='utf-8'); tmp.replace(target/'leagues.json')
        (rel/'registry.json').write_text(json.dumps(registry,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        league_registry.reload(); model_registry.clear()
        registry_errors=league_registry.validate(); model_results=model_registry.validate_all()
        bad=[r for r in model_results if not r.get('ok') and r.get('league_slug') in changed]
        if registry_errors or bad:
            raise ValueError('Release validation failed: '+json.dumps({'registry_errors':registry_errors,'models':bad})[:4000])
        (rel/'release.json').write_text(json.dumps({'release_key':release_key,'changed_models':changed},indent=2))
        return {'ok':True,'release_key':release_key,'changed_models':changed,'registered_leagues':len(league_registry.enabled_slugs())}
    except Exception:
        # Restore only folders touched by this attempt.
        for slug in changed:
            dst=target/slug; shutil.rmtree(dst,ignore_errors=True)
            if (backup/slug).exists(): shutil.copytree(backup/slug,dst)
        if (backup/'leagues.json').exists(): shutil.copy2(backup/'leagues.json',target/'leagues.json')
        league_registry.reload(); model_registry.clear()
        raise

def rollback_release(release_key: str) -> dict[str, Any]:
    rel=RELEASE_ROOT/release_key
    reg=rel/'registry.json'
    extracted=rel/'extract'
    if not reg.exists() or not extracted.exists(): raise FileNotFoundError('Release snapshot is not available on this service.')
    incoming=_models_dir(extracted); target=model_root_path(); changed=[]
    for src in incoming.iterdir():
        if not src.is_dir() or not (src/'model_config.json').exists(): continue
        dst=target/src.name; shutil.rmtree(dst,ignore_errors=True); shutil.copytree(src,dst); changed.append(src.name)
    shutil.copy2(reg,target/'leagues.json')
    league_registry.reload(); model_registry.clear()
    errors=league_registry.validate(); bad=[r for r in model_registry.validate_all() if not r.get('ok') and r.get('league_slug') in changed]
    if errors or bad: raise ValueError('Rollback validation failed: '+json.dumps({'registry_errors':errors,'models':bad})[:4000])
    return {'ok':True,'release_key':release_key,'restored_models':changed,'registered_leagues':len(league_registry.enabled_slugs())}
