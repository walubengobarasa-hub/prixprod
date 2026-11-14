"""Prepare/check a commit-pinned model manifest for Git LFS + GitHub Releases.

Usage:
  python scripts/prepare_github_models.py --write
  python scripts/prepare_github_models.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "deploy_models"


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as reader:
        for part in iter(lambda: reader.read(1024 * 1024), b""):
            sha.update(part)
    return sha.hexdigest()


def prepare(expected_version: str = "1.6.1") -> dict:
    registry = BASE / "leagues.json"
    if not registry.is_file():
        raise ValueError("Missing deploy_models/leagues.json (the six new England entries go here)")
    data = json.loads(registry.read_text(encoding="utf-8"))
    leagues = data.get("leagues", data)
    if not isinstance(leagues, dict) or not leagues:
        raise ValueError("The Git registry delta must be a nonempty mapping of leagues")
    import re
    slug_re = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    files: dict[str, dict] = {}
    folders: set[str] = set()
    for slug, meta in leagues.items():
        if not slug_re.fullmatch(slug) or not isinstance(meta, dict):
            raise ValueError(f"Unsafe/invalid league: {slug}")
        if meta.get("alias_for"):
            continue
        folder = meta.get("model_folder", slug)
        if not slug_re.fullmatch(folder):
            raise ValueError(f"Unsafe model_folder: {folder!r}")
        folders.add(folder)
        root = BASE / "models" / folder
        if not root.is_dir():
            raise ValueError(f"Missing model folder: {root}")
        cfgpath, metapath = root / "model_config.json", root / "model_metadata_v064.json"
        cfg, info = json.loads(cfgpath.read_text()), json.loads(metapath.read_text())
        if cfg.get("league_slug") != folder or info.get("league_slug") != folder:
            raise ValueError(f"Bad league_slug in {folder} metadata")
        if info.get("sklearn_training_version") != expected_version:
            raise ValueError(f"{folder}: model version is not {expected_version}")
        models = cfg.get("models", {})
        if not isinstance(models, dict) or not models:
            raise ValueError(f"{folder}: no trained model artifacts listed")
        expected_files = list(models.values()) + [cfg.get("feature_columns_file") or "feature_columns.json", "model_config.json", "model_metadata_v064.json"]
        for filename in expected_files:
            if not isinstance(filename, str) or Path(filename).name != filename or not (root / filename).is_file():
                raise ValueError(f"{folder}: missing/unsafe {filename!r}")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Model symlink rejected: {path}")
            if path.is_file():
                rel = path.relative_to(BASE / "models").as_posix()
                with path.open("rb") as stream:
                    if stream.read(48).startswith(b"version https://git-lfs.github.com/spec/v1"):
                        raise ValueError(f"File is an undownloaded Git LFS pointer: {rel}")
                files[rel] = {"sha256": digest(path), "size": path.stat().st_size}
    extras = {x.name for x in (BASE / "models").iterdir() if x.is_dir()} - folders
    if extras:
        raise ValueError(f"Model folders missing from registry delta: {sorted(extras)}")
    return {"format": 1, "registry_sha256": digest(registry), "files": files, "folders": sorted(folders)}


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--sklearn-version", default="1.6.1")
    args = parser.parse_args()
    result = prepare(args.sklearn_version)
    manifest_file = BASE / "model_manifest.json"
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.write:
        manifest_file.write_text(serialized, encoding="utf-8")
        print(f"Wrote {manifest_file} ({len(result['folders'])} leagues; {len(result['files'])} model files)")
    else:
        if not manifest_file.is_file() or manifest_file.read_text(encoding="utf-8") != serialized:
            raise SystemExit("Model manifest missing/stale; run python scripts/prepare_github_models.py --write and commit it")
        print(f"Manifest verified: {len(result['folders'])} league folders, {len(result['files'])} files")


if __name__ == "__main__":
    main()
