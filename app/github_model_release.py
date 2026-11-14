"""Retrieve GitHub Release model artifacts before the existing safe disk sync.

GitHub Actions publishes a release ZIP from the LFS-backed deploy_models/models
on every push to main. Render downloads it *at runtime*, because its persistent
Disk is unavailable during build/pre-deploy. Models are verified against the
commit-tracked deploy_models/model_manifest.json before live folders change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import requests

from app.git_model_sync import _load_registry, _safe_slug, sync_git_models

LOG = logging.getLogger("prix.github_model_release")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TAG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ASSET_NAME = "prix-models.zip"
DEFAULT_LIMIT = 2 * 1024**3


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest(root: Path) -> dict:
    path = root / "deploy_models" / "model_manifest.json"
    if not path.is_file():
        raise ValueError(f"Missing {path}; run python scripts/prepare_github_models.py --write")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("Invalid model_manifest.json structure")
    registry_path = root / "deploy_models" / "leagues.json"
    if manifest.get("registry_sha256") != _sha256_file(registry_path):
        raise ValueError("Model manifest does not match this Git commit's leagues.json")
    return manifest


def _download_release_zip(repo: str, tag: str, archive: Path, *, timeout: int = 120) -> dict:
    if not REPO_RE.fullmatch(repo) or not TAG_RE.fullmatch(tag):
        raise ValueError("Invalid GitHub repository or release tag")
    token = os.getenv("PRIX_GITHUB_MODEL_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    with requests.Session() as session:
        release_response = session.get(api, headers=headers, timeout=30)
        release_response.raise_for_status()
        release = release_response.json()
        assets = [a for a in release.get("assets", []) if a.get("name") == ASSET_NAME and a.get("state") == "uploaded"]
        if len(assets) != 1:
            raise ValueError(f"GitHub Release {tag!r} must contain exactly one uploaded {ASSET_NAME}")
        asset = assets[0]
        expected_size = int(asset.get("size") or 0)
        max_size = int(os.getenv("PRIX_GITHUB_MAX_ARCHIVE_BYTES", str(DEFAULT_LIMIT)))
        if expected_size <= 0 or expected_size > max_size:
            raise ValueError(f"Release asset size invalid or exceeds {max_size} bytes")
        binary_headers = {**headers, "Accept": "application/octet-stream"}
        with session.get(asset["url"], headers=binary_headers, stream=True, timeout=(30, timeout)) as response:
            response.raise_for_status()
            if "application/json" in response.headers.get("Content-Type", "").lower():
                raise ValueError("GitHub returned JSON instead of Release asset; check token and permissions")
            downloaded = 0
            digest = hashlib.sha256()
            with archive.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > max_size:
                        raise ValueError("GitHub model release archive is larger than the configured limit")
                    stream.write(chunk)
                    digest.update(chunk)
        if downloaded != expected_size:
            raise ValueError(f"Incomplete release download: expected {expected_size} bytes, got {downloaded}")
        gh_digest = str(asset.get("digest") or "")
        if gh_digest.startswith("sha256:") and gh_digest[7:] != digest.hexdigest():
            raise ValueError("Release asset SHA-256 differs from GitHub's asset digest")
        return {"release_tag": tag, "release_asset_id": asset.get("id"), "archive_sha256": digest.hexdigest(), "download_bytes": downloaded}


def _extract_verified(archive: Path, output: Path, manifest: dict) -> None:
    tracked = manifest["files"]
    if not tracked:
        raise ValueError("Model manifest has no model files")
    seen = set()
    extracted_bytes = 0
    max_extract = int(os.getenv("PRIX_GITHUB_MAX_EXTRACT_BYTES", str(5 * 1024**3)))
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            name = member.filename
            if member.is_dir():
                continue
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or "\\" in name or
                    len(path.parts) < 3 or path.parts[0] != "models"):
                raise ValueError(f"Unsafe or unexpected Release archive entry: {name!r}")
            _safe_slug(path.parts[1])
            if stat.S_IFMT(member.external_attr >> 16) == stat.S_IFLNK:
                raise ValueError(f"Symlink not allowed in Release archive: {name}")
            relative = "/".join(path.parts[1:])
            if relative not in tracked or relative in seen:
                raise ValueError(f"Untracked/duplicate Release file: {name}")
            extracted_bytes += member.file_size
            if extracted_bytes > max_extract:
                raise ValueError("Uncompressed Release archive exceeds size limit")
            target = output.joinpath(*path.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            written = 0
            with z.open(member) as src, target.open("wb") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(chunk)
                    h.update(chunk)
                    written += len(chunk)
            expected = tracked[relative]
            if written != expected["size"] or h.hexdigest() != expected["sha256"]:
                raise ValueError(f"Release model file mismatch: {relative}")
            seen.add(relative)
    missing = set(tracked) - seen
    if missing:
        raise ValueError(f"Model Release missing {len(missing)} file(s): {sorted(missing)[:5]}")



def _cached_install_is_current(root: Path, disk: Path, manifest: dict, tag: str) -> bool:
    """Avoid re-downloading large models if the exact verified files remain on disk."""
    receipt = disk / ".prix_github_models_receipt.json"
    if not receipt.is_file():
        return False
    try:
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        if saved.get("manifest_sha256") != _sha256_file(root / "deploy_models" / "model_manifest.json") or saved.get("release_tag") != tag:
            return False
        local = _load_registry(root / "deploy_models" / "leagues.json")["leagues"]
        live = _load_registry(disk / "leagues.json")["leagues"]
        if any(live.get(slug) != data for slug, data in local.items()):
            return False
        for relative, record in manifest["files"].items():
            path = disk / relative
            if not path.is_file() or path.is_symlink() or path.stat().st_size != record["size"]:
                return False
            if _sha256_file(path) != record["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _save_receipt(root: Path, disk: Path, tag: str, release: dict) -> None:
    receipt = disk / ".prix_github_models_receipt.json"
    new = {
        "manifest_sha256": _sha256_file(root / "deploy_models" / "model_manifest.json"),
        "release_tag": tag,
        "archive_sha256": release["archive_sha256"],
    }
    temp = disk / ".prix_github_models_receipt.tmp"
    temp.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, receipt)

def sync_render_models() -> dict:
    """Main startup entrypoint. Local Git models supported for offline testing."""
    from app.config import model_root_path, project_root
    root = project_root()
    deploy = root / "deploy_models"
    if not (deploy / "leagues.json").is_file():
        return {"ok": True, "enabled": False, "reason": "No deploy_models/leagues.json in this checkout"}

    repo = os.getenv("PRIX_GITHUB_MODEL_REPO", "").strip() or os.getenv("RENDER_GIT_REPO_SLUG", "").strip()
    if not repo:
        # Local developer path uses the checked-out source model folders.
        return sync_git_models(repo_root=root, disk_root=model_root_path())

    tag = os.getenv("PRIX_GITHUB_MODEL_RELEASE_TAG", "prix-models-latest").strip()
    manifest = _manifest(root)
    disk = model_root_path()
    disk.mkdir(parents=True, exist_ok=True)
    if os.getenv("PRIX_GITHUB_FORCE_SYNC", "0") != "1" and _cached_install_is_current(root, disk, manifest, tag):
        count = len(_load_registry(disk / "leagues.json")["leagues"])
        return {"ok": True, "enabled": True, "source": "github_release_cached", "release_tag": tag,
                "registry_entries_after": count, "registry_updated": False,
                "installed": [], "replaced": [], "unchanged": manifest["folders"],
                "disk_root": str(disk)}
    # Temporary files live on the persistent disk to avoid Render /tmp space pressure.
    with tempfile.TemporaryDirectory(prefix=".prix_release_fetch_", dir=disk) as temp:
        tempdir = Path(temp)
        archive = tempdir / ASSET_NAME
        release = _download_release_zip(repo, tag, archive)
        folder = tempdir / "source_models"
        folder.mkdir()
        _extract_verified(archive, folder, manifest)
        status = sync_git_models(repo_root=root, disk_root=disk, source_models_override=folder)
        _save_receipt(root, disk, tag, release)
    return {**status, "source": "github_release", **release}
