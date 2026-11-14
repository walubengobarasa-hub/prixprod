"""Merge model artifacts shipped in Git into the Render persistent model directory.

This module is called before LeagueRegistry is imported in app/main.py. It does
not train models, modify market approvals, or contact external APIs.

Source layout:
  deploy_models/leagues.json        # additions/updates, not a replacement registry
  deploy_models/models/<slug>/...   # the trained artifacts for these new entries

Fail closed: validation takes place before any live registry is written. New
model folders are installed atomically; existing folders require explicit opt-in
for replacement. On a late failure, changes are rolled back.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("prix.git_model_sync")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


def _load_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"leagues": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Registry must be an object: {path}")
    leagues = data.get("leagues", data)
    if not isinstance(leagues, dict):
        raise ValueError(f"Registry leagues must be a mapping: {path}")
    return {**{key: val for key, val in data.items() if key != "leagues"}, "leagues": leagues}


def _safe_slug(name: str) -> str:
    if not isinstance(name, str) or not SLUG.fullmatch(name):
        raise ValueError(f"Unsafe league/model folder name: {name!r}")
    return name


def _safe_tree(folder: Path) -> None:
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError(f"Model directory is missing or a symlink: {folder}")
    for item in folder.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"Symlink not allowed in model folder: {item}")
        if not item.is_file() and not item.is_dir():
            raise ValueError(f"Non-regular file in model folder: {item}")


def _validate_source_model(folder: Path, slug: str, sklearn_version: str) -> None:
    _safe_tree(folder)
    cfgfile = folder / "model_config.json"
    metafile = folder / "model_metadata_v064.json"
    if not cfgfile.is_file() or not metafile.is_file():
        raise ValueError(f"{slug}: model_config.json and model_metadata_v064.json are required")
    cfg = json.loads(cfgfile.read_text(encoding="utf-8"))
    meta = json.loads(metafile.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or not isinstance(meta, dict):
        raise ValueError(f"{slug}: invalid model metadata/config format")
    if cfg.get("league_slug") != slug or meta.get("league_slug") != slug:
        raise ValueError(f"{slug}: league_slug mismatch in model_config or metadata")
    actual_training_version = str(meta.get("sklearn_training_version") or "").strip()
    if not actual_training_version or actual_training_version != sklearn_version:
        raise ValueError(
            f"{slug}: trained sklearn={actual_training_version or 'UNSPECIFIED'} "
            f"but Render runtime={sklearn_version}; retrain using the serving version"
        )
    feat = str(cfg.get("feature_columns_file") or "feature_columns.json")
    if Path(feat).name != feat or not (folder / feat).is_file():
        raise ValueError(f"{slug}: missing/unsafe feature columns file {feat!r}")
    models = cfg.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError(f"{slug}: no model artifacts specified")
    for market, name in models.items():
        if not isinstance(name, str) or Path(name).name != name or not (folder / name).is_file():
            raise ValueError(f"{slug}: missing/unsafe artifact for {market}: {name}")
        # Guard against Git LFS pointer files that weren't downloaded at build time.
        if (folder / name).stat().st_size < 200:
            head = (folder / name).read_bytes()[:80]
            if head.startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise ValueError(f"{slug}: Git LFS pointer instead of model artifact: {name}")


def _folder_digest(folder: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(item.relative_to(folder).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as stream:
            for part in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(part)
    return digest.hexdigest()


def _validate_merged(leagues: dict[str, Any], disk_root: Path, source_models: Path,
                     updated: set[str]) -> None:
    # Equivalent to the core enabled-league checks in LeagueRegistry.validate,
    # additionally guarding slugs, unsafe folder paths and changed models.
    season_owners: dict[str, str] = {}
    for slug, raw in leagues.items():
        _safe_slug(slug)
        if not isinstance(raw, dict):
            raise ValueError(f"{slug}: registry record must be an object")
        if not bool(raw.get("enabled", True)):
            continue
        alias = raw.get("alias_for")
        if alias:
            if alias not in leagues:
                raise ValueError(f"{slug}: alias points to missing {alias}")
            continue
        folder = _safe_slug(raw.get("model_folder") or slug)
        source = source_models / folder
        active = disk_root / folder
        if folder not in updated and not active.is_dir():
            raise ValueError(f"{slug}: active model folder missing: {active}")
        if folder in updated and not source.is_dir():
            raise ValueError(f"{slug}: git model folder missing: {source}")
        if folder in updated:
            source_cfg = json.loads((source / "model_config.json").read_text(encoding="utf-8"))
            for field in ("model_family", "model_version"):
                declared, packaged = raw.get(field), source_cfg.get(field)
                if declared and packaged and str(declared) != str(packaged):
                    raise ValueError(f"{slug}: {field} differs: registry={declared}, model={packaged}")
        season = raw.get("footystats_season_id") or raw.get("footystats_league_id")
        if not season:
            raise ValueError(f"{slug}: missing FootyStats season ID")
        season = str(season)
        if season in season_owners and season_owners[season] != slug:
            raise ValueError(f"{slug}: FootyStats ID {season} duplicates {season_owners[season]}")
        season_owners[season] = slug


@contextmanager
def _deployment_lock(disk_root: Path):
    # Render persistent disks are mounted at runtime. Linux flock ensures two
    # uvicorn workers do not race to write the registry/folders.
    lock_path = disk_root / ".prix_git_model_sync.lock"
    with lock_path.open("a+b") as lock:
        try:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass  # Windows local smoke tests normally run one process
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass


def sync_git_models(
    repo_root: Path | str | None = None,
    disk_root: Path | str | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply Git-declared league additions while preserving persistent models.

    A missing deploy_models/leagues.json is a harmless no-op, so this patch can
    be deployed before trained model artifacts are available.
    """
    if repo_root is None or disk_root is None:
        from app.config import model_root_path, project_root
        repo_root = project_root() if repo_root is None else repo_root
        disk_root = model_root_path() if disk_root is None else disk_root
    repo_root = Path(repo_root).resolve()
    disk_root = Path(disk_root).resolve()
    source = repo_root / "deploy_models"
    source_registry_path = source / "leagues.json"
    if _flag("PRIX_GIT_MODEL_SYNC_DISABLED"):
        return {"ok": True, "enabled": False, "reason": "PRIX_GIT_MODEL_SYNC_DISABLED"}
    if not source_registry_path.exists():
        return {"ok": True, "enabled": False,
                "reason": "No deploy_models/leagues.json committed yet"}
    if disk_root == (repo_root / "deploy_models").resolve():
        raise ValueError("Configured model root cannot be the Git source directory")
    if disk_root == (repo_root / "models").resolve() and _flag("PRIX_REQUIRE_PERSISTENT_MODEL_ROOT", True):
        raise RuntimeError("Model root fell back to ephemeral ./models. Check MODEL_ROOT and Render disk mount")

    source_models = source / "models"
    delta = _load_registry(source_registry_path)["leagues"]
    if not delta:
        raise ValueError("deploy_models/leagues.json has no league entries")
    for slug in delta:
        _safe_slug(slug)
    disk_root.mkdir(parents=True, exist_ok=True)
    runtime_sklearn = importlib.metadata.version("scikit-learn")
    expected_sklearn = os.getenv("PRIX_EXPECTED_SKLEARN_VERSION", "1.6.1").strip()
    if runtime_sklearn != expected_sklearn:
        raise RuntimeError(
            f"Render sklearn={runtime_sklearn}, expected={expected_sklearn}; "
            "refusing model sync. Match requirements.txt to the trained artifact version"
        )

    with _deployment_lock(disk_root):
        live_registry_path = disk_root / "leagues.json"
        current = _load_registry(live_registry_path)
        previous = current["leagues"]
        minimum = int(os.getenv("PRIX_GIT_SYNC_MIN_BASE_ENTRIES", "67"))
        if len(previous) < minimum:
            raise ValueError(
                f"Live registry has {len(previous)} entries; expected at least {minimum}. "
                "Do not bootstrap a partial registry onto an empty disk"
            )
        merged = dict(previous)
        merged.update(delta)
        merged_registry = {**current, "leagues": merged}
        referenced_folders = {
            _safe_slug(meta.get("model_folder") or slug)
            for slug, meta in delta.items()
            if isinstance(meta, dict) and not meta.get("alias_for")
        }
        source_folders = {
            p.name for p in source_models.iterdir() if p.is_dir()
        } if source_models.is_dir() else set()
        extra = source_folders - referenced_folders
        if extra:
            raise ValueError(f"Git model folders not referenced in registry additions: {sorted(extra)}")
        for folder in source_folders:
            _safe_slug(folder)
            _validate_source_model(source_models / folder, folder, runtime_sklearn)

        _validate_merged(merged, disk_root, source_models, source_folders)

        installs: list[str] = []
        replaces: list[str] = []
        skips: list[str] = []
        for folder in sorted(source_folders):
            active = disk_root / folder
            if not active.exists():
                installs.append(folder)
            elif _folder_digest(active) == _folder_digest(source_models / folder):
                skips.append(folder)
            else:
                if not _flag("PRIX_GIT_SYNC_REPLACE_EXISTING"):
                    raise ValueError(
                        f"{folder}: model folder differs from Git and already exists. "
                        "Replacement is blocked by default. Explicitly set "
                        "PRIX_GIT_SYNC_REPLACE_EXISTING=1 to permit backed-up replacements."
                    )
                replaces.append(folder)

        serialized = (json.dumps(merged_registry, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        current_bytes = live_registry_path.read_bytes() if live_registry_path.is_file() else None
        registry_changed = current_bytes != serialized
        status = {
            "ok": True, "enabled": True,
            "runtime_sklearn": runtime_sklearn,
            "registry_entries_before": len(previous),
            "registry_entries_after": len(merged),
            "registry_updated": registry_changed,
            "installed": installs, "replaced": replaces, "unchanged": skips,
            "disk_root": str(disk_root),
            "dry_run": dry_run,
        }
        if dry_run or (not registry_changed and not installs and not replaces):
            LOG.info("Git model sync: %s", status)
            return status

        backup_base = disk_root / ".prix_git_sync_backups"
        backup_base.mkdir(parents=True, exist_ok=True)
        release_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + os.urandom(3).hex()
        backup = backup_base / release_tag
        backup.mkdir()
        stage_parent = Path(tempfile.mkdtemp(prefix=".prix_git_stage_", dir=disk_root))
        moved_existing: list[str] = []
        installed_live: list[str] = []
        written_registry = False
        try:
            # Prepare every target on the same filesystem, before mutating live paths.
            for folder in installs + replaces:
                shutil.copytree(source_models / folder, stage_parent / folder)
                _validate_source_model(stage_parent / folder, folder, runtime_sklearn)
            if current_bytes is not None:
                (backup / "leagues.json").write_bytes(current_bytes)
            (stage_parent / "leagues.json").write_bytes(serialized)
            for folder in replaces:
                os.replace(disk_root / folder, backup / folder)
                moved_existing.append(folder)
            for folder in installs + replaces:
                os.replace(stage_parent / folder, disk_root / folder)
                installed_live.append(folder)
            os.replace(stage_parent / "leagues.json", live_registry_path)
            written_registry = True
        except Exception:
            if written_registry or installed_live or moved_existing:
                if current_bytes is not None:
                    restore_tmp = disk_root / f".leagues-restore-{release_tag}.json"
                    restore_tmp.write_bytes(current_bytes)
                    os.replace(restore_tmp, live_registry_path)
                elif live_registry_path.exists():
                    live_registry_path.unlink()
                for folder in reversed(installed_live):
                    shutil.rmtree(disk_root / folder, ignore_errors=True)
                for folder in reversed(moved_existing):
                    os.replace(backup / folder, disk_root / folder)
            raise
        finally:
            shutil.rmtree(stage_parent, ignore_errors=True)
        status["backup_path"] = str(backup)
        LOG.info("Git model sync applied: %s", status)
        return status


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Safe Git to Render model sync preflight")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--disk", help="Existing persistent model directory; defaults to MODEL_ROOT")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    target = args.disk
    if target is None:
        from app.config import model_root_path
        target = model_root_path()
    print(json.dumps(sync_git_models(args.repo, target, dry_run=args.dry_run), indent=2))
