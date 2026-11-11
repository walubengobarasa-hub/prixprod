"""One-release, bounded-memory replacement of seven v0.6.4 candidate folders.

Never touches leagues.json or other models. Only accepts the audited Colab
artifact with an exact SHA256 digest, and preserves old folders for rollback.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.config import model_root_path
from app.model_folder_installer import NEW_CANDIDATE_FAMILIES, _check_model

EXPECTED_SHA256 = "b26e3d6e7e59566d0c8c0fc31a4f13f8a206a186fa4be69a955476f2e4174367"
EXPECTED_SKLEARN = "1.6.1"
EXPECTED_SLUGS = frozenset(NEW_CANDIDATE_FAMILIES)
MAX_ARCHIVE_BYTES = 60 * 1024 * 1024
MAX_UNPACKED_BYTES = 240 * 1024 * 1024
BACKUP_NAME = ".prix-seven-candidate-backups"
LOCK_NAME = ".prix-seven-candidate-update.lock"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _assert_runtime():
    actual = importlib.metadata.version("scikit-learn")
    if actual != EXPECTED_SKLEARN:
        raise ValueError(f"Serving scikit-learn is {actual}; expected {EXPECTED_SKLEARN}. No files changed.")


def _validate_live_registry(root: Path):
    path = root / "leagues.json"
    if not path.is_file():
        raise ValueError("Active leagues.json missing; no files changed")
    registry = json.loads(path.read_text(encoding="utf-8"))
    entries = registry.get("leagues", {})
    if not isinstance(entries, dict) or any(slug not in entries for slug in EXPECTED_SLUGS):
        raise ValueError("Live registry does not contain all seven candidate slugs")
    for slug in EXPECTED_SLUGS:
        entry = entries[slug]
        if not entry.get("enabled", False) or entry.get("model_folder") != slug:
            raise ValueError(f"Registry entry {slug} is not enabled or model_folder mismatches")
    return _sha256(path)


def _extract_and_validate(archive: Path, stage: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        files = [x for x in zf.infolist() if not x.is_dir()]
        if len(files) > 400 or not files:
            raise ValueError("Unexpected number of model archive files")
        if sum(x.file_size for x in files) > MAX_UNPACKED_BYTES:
            raise ValueError("Uncompressed archive exceeds 240 MiB")
        seen: set[str] = set()
        folders: set[str] = set()
        for entry in zf.infolist():
            name = entry.filename
            parts = PurePosixPath(name).parts
            if (
                not parts or name.startswith("/") or "\\" in name or ".." in parts
                or len(parts) != 2 or parts[0] not in EXPECTED_SLUGS
                or (entry.flag_bits & 1)
                or stat.S_ISLNK((entry.external_attr >> 16) & 0xffff)
                or (not entry.is_dir() and not parts[1].endswith((".pkl", ".json", ".csv")))
            ):
                raise ValueError(f"Unexpected or unsafe ZIP member: {name}")
            if entry.is_dir():
                continue
            if name in seen:
                raise ValueError(f"Duplicate ZIP member: {name}")
            seen.add(name)
            folders.add(parts[0])
            final = stage / parts[0] / parts[1]
            final.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(entry) as r, final.open("wb") as w:
                shutil.copyfileobj(r, w, 1024 * 1024)
        if folders != EXPECTED_SLUGS:
            raise ValueError("Archive must contain exactly the seven trained candidate directories")
    for slug in sorted(EXPECTED_SLUGS):
        path = stage / slug
        _check_model(path)
        cfg = json.loads((path / "model_config.json").read_text(encoding="utf-8"))
        meta = json.loads((path / "model_metadata_v064.json").read_text(encoding="utf-8"))
        cols = json.loads((path / "feature_columns.json").read_text(encoding="utf-8"))
        if meta.get("sklearn_training_version") != EXPECTED_SKLEARN:
            raise ValueError(f"{slug}: training version mismatch")
        if meta.get("candidate_only") is not True or meta.get("deployment_status") != "pending_validation":
            raise ValueError(f"{slug}: unexpected candidate approval metadata")
        if cfg.get("enabled") is not False or len(cfg.get("models", {})) != 11:
            raise ValueError(f"{slug}: unexpected candidate configuration")
        if len(cols) != 400:
            raise ValueError(f"{slug}: expected exactly 400 features")
        if any(rule.get("status") not in {"review_only", "explainability_only"} for rule in cfg.get("market_rules", {}).values()):
            raise ValueError(f"{slug}: unexpected approved market in candidate release")


def _acquire_lock(root: Path):
    lock = root / LOCK_NAME
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("Another candidate release operation is active (or a stale lock exists)")
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))
    return lock


def replace_seven_candidates(archive: Path, root: Path | None = None) -> dict:
    target = root if root is not None else model_root_path()
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP upload exceeds 60 MiB")
    digest = _sha256(archive)
    if digest != EXPECTED_SHA256:
        raise ValueError("Archive checksum differs from audited 1.6.1 retraining release")
    # Incoming models expand to ~144 MB; fail safely instead of exhausting the disk.
    if shutil.disk_usage(target).free < 180 * 1024 * 1024:
        raise ValueError("Persistent model disk needs at least 180 MiB free for staged replacement")
    _assert_runtime()
    lock = _acquire_lock(target)
    try:
        registry_hash = _validate_live_registry(target)
        for slug in EXPECTED_SLUGS:
            current = target / slug
            if not current.is_dir():
                raise ValueError(f"Existing model folder missing: {slug}")
            metadata = current / "model_metadata_v064.json"
            if metadata.exists():
                current_ver = json.loads(metadata.read_text(encoding="utf-8")).get("sklearn_training_version")
                if current_ver == EXPECTED_SKLEARN:
                    raise ValueError(f"{slug} already has scikit-learn 1.6.1; refusing duplicate replacement")
        with tempfile.TemporaryDirectory(prefix=".prix-seven-stage-", dir=target) as tmp:
            stage = Path(tmp)
            _extract_and_validate(archive, stage)
            if _validate_live_registry(target) != registry_hash:
                raise ValueError("Registry changed during upload; retry after a stable backup")
            backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
            backup = target / BACKUP_NAME / backup_id
            backup.mkdir(parents=True, exist_ok=False)
            moved_old: list[str] = []
            deployed: list[str] = []
            try:
                for slug in sorted(EXPECTED_SLUGS):
                    os.rename(target / slug, backup / slug)
                    moved_old.append(slug)
                    os.rename(stage / slug, target / slug)
                    deployed.append(slug)
                if _validate_live_registry(target) != registry_hash:
                    raise ValueError("Registry changed during replacement")
                (backup / "manifest.json").write_text(json.dumps({
                    "backup_id": backup_id, "release_sha256": digest,
                    "registry_sha256": registry_hash, "folders": sorted(EXPECTED_SLUGS),
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "replaced", "sklearn_training_version": EXPECTED_SKLEARN,
                }, indent=2), encoding="utf-8")
            except Exception:
                for slug in reversed(deployed):
                    if (target / slug).exists():
                        shutil.rmtree(target / slug)
                for slug in reversed(moved_old):
                    if (backup / slug).exists():
                        os.rename(backup / slug, target / slug)
                shutil.rmtree(backup, ignore_errors=True)
                raise
            return {
                "ok": True, "replaced_folders": sorted(EXPECTED_SLUGS),
                "replaced_count": len(EXPECTED_SLUGS), "archive_sha256": digest,
                "backup_id": backup_id, "model_root": str(target),
                "registry_untouched": True, "restart_recommended": True,
                "market_approval_changed": False,
            }
    finally:
        lock.unlink(missing_ok=True)


def rollback_seven_candidates(backup_id: str, root: Path | None = None) -> dict:
    if not re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", backup_id):
        raise ValueError("Invalid backup_id")
    target = Path(root) if root is not None else model_root_path()
    lock = _acquire_lock(target)
    try:
        backup = target / BACKUP_NAME / backup_id
        manifest_path = backup / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("Rollback manifest not found")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "replaced" or set(manifest.get("folders", [])) != EXPECTED_SLUGS:
            raise ValueError("Snapshot is not an available seven-model replacement backup")
        if _validate_live_registry(target) != manifest.get("registry_sha256"):
            raise ValueError("Active registry changed since replacement; manual review required")
        for slug in EXPECTED_SLUGS:
            if not (target / slug).is_dir() or not (backup / slug).is_dir():
                raise ValueError(f"Rollback cannot safely locate both versions of {slug}")
        with tempfile.TemporaryDirectory(prefix=".prix-rollback-seven-", dir=target) as tmp:
            displaced = Path(tmp)
            moved: list[str] = []
            restored: list[str] = []
            try:
                for slug in sorted(EXPECTED_SLUGS):
                    os.rename(target / slug, displaced / slug)
                    moved.append(slug)
                    os.rename(backup / slug, target / slug)
                    restored.append(slug)
                manifest["status"] = "rolled_back"
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            except Exception:
                for slug in reversed(restored):
                    if (target / slug).exists():
                        os.rename(target / slug, backup / slug)
                for slug in reversed(moved):
                    if (displaced / slug).exists():
                        os.rename(displaced / slug, target / slug)
                raise
        return {"ok": True, "restored_folders": sorted(EXPECTED_SLUGS),
                "registry_untouched": True, "restart_recommended": True}
    finally:
        lock.unlink(missing_ok=True)
