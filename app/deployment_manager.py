from __future__ import annotations
import base64, json, re, shutil, tempfile, zipfile
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
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,96}', release_key):
        raise ValueError('Invalid release_key. Use letters, digits, hyphens, or underscores.')
    rel = RELEASE_ROOT / release_key
    if rel.exists():
        raise ValueError('Release key already exists; refusing to replace a recovery snapshot.')
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
        if (backup/'leagues.json').exists():
            shutil.copy2(backup/'leagues.json',target/'leagues.json')
        else:
            (target/'leagues.json').unlink(missing_ok=True)
        league_registry.reload(); model_registry.clear()
        raise

def rollback_release(release_key: str) -> dict[str, Any]:
    """Restore the pre-deployment snapshot, not the newly deployed release.

    New model folders absent before deployment are removed; older folders and
    leagues.json are restored from RELEASE_ROOT/<key>/backup. A temporary
    rollback snapshot allows recovery if validation of the restore fails.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", release_key):
        raise ValueError("Invalid release_key")
    rel = RELEASE_ROOT / release_key
    manifest = rel / "release.json"
    backup = rel / "backup"
    if not manifest.is_file() or not backup.is_dir():
        raise FileNotFoundError("Completed release backup is not available on this service")
    changed = json.loads(manifest.read_text(encoding="utf-8")).get("changed_models") or []
    if not changed or any(not isinstance(slug, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", slug) for slug in changed):
        raise ValueError("Unsafe or empty release snapshot")
    target = model_root_path()
    if not target.is_dir():
        raise FileNotFoundError("Model root is missing")
    with tempfile.TemporaryDirectory(prefix=".prix-rollback-", dir=target) as tmp:
        before_rollback = Path(tmp)
        old_registry = target / "leagues.json"
        if old_registry.exists():
            shutil.copy2(old_registry, before_rollback / "leagues.json")
        for slug in changed:
            folder = target / slug
            if folder.exists():
                shutil.copytree(folder, before_rollback / slug)
        try:
            for slug in changed:
                dst = target / slug
                shutil.rmtree(dst, ignore_errors=True)
                if (backup / slug).is_dir():
                    shutil.copytree(backup / slug, dst)
            if (backup / "leagues.json").is_file():
                shutil.copy2(backup / "leagues.json", target / "leagues.json")
            else:
                (target / "leagues.json").unlink(missing_ok=True)
            league_registry.reload()
            model_registry.clear()
            errors = league_registry.validate()
            if errors:
                raise ValueError("Rolled-back registry validation failed: " + json.dumps(errors)[:1200])
        except Exception:
            # Put the currently deployed release back if rollback itself failed.
            for slug in changed:
                dst = target / slug
                shutil.rmtree(dst, ignore_errors=True)
                if (before_rollback / slug).is_dir():
                    shutil.copytree(before_rollback / slug, dst)
            if (before_rollback / "leagues.json").is_file():
                shutil.copy2(before_rollback / "leagues.json", target / "leagues.json")
            else:
                (target / "leagues.json").unlink(missing_ok=True)
            league_registry.reload()
            model_registry.clear()
            raise
    return {
        "ok": True,
        "release_key": release_key,
        "restored_models": [slug for slug in changed if (backup / slug).is_dir()],
        "removed_new_models": [slug for slug in changed if not (backup / slug).is_dir()],
        "registered_leagues": len(league_registry.enabled_slugs()),
    }
