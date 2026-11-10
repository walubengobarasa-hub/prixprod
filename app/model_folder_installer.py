"""Memory-bounded, install-only model artifact handler for known Prix folders.

Only the fixed set of known v0.6.4 slugs is accepted. Never overwrites models.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from app.config import model_root_path

LEGACY_FOLDERS = frozenset({
    "georgia", "greece", "hungary", "mexico", "netherlands", "northern_ireland",
    "romania", "usa", "ucl", "uecl",
})
NEW_CANDIDATE_FAMILIES = {
    "denmark-1st-division": "league_v064",
    "england-efl-trophy": "domestic_cup_v1",
    "europe-uefa-women-s-champions-league": "continental_cup_v1",
    "international-africa-cup-of-nations-qualification": "international_competition_v1",
    "international-concacaf-nations-league": "international_competition_v1",
    "international-uefa-nations-league": "international_competition_v1",
    "jamaica-jamaica-national-premier-league": "league_v064",
}
ALLOWED_MISSING_FOLDERS = LEGACY_FOLDERS | frozenset(NEW_CANDIDATE_FAMILIES)
MAX_ARCHIVE_BYTES = 60 * 1024 * 1024
MAX_EXPANDED_BYTES = 240 * 1024 * 1024
MAX_ARCHIVE_FILES = 1200


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((member.external_attr >> 16) & 0xFFFF)


def _check_model(folder: Path) -> None:
    config_file = folder / "model_config.json"
    if not config_file.is_file():
        raise ValueError(f"{folder.name}: missing model_config.json")
    data = json.loads(config_file.read_text(encoding="utf-8"))
    if str(data.get("league_slug") or "") != folder.name:
        raise ValueError(f"{folder.name}: model_config league_slug mismatch")
    if folder.name in LEGACY_FOLDERS:
        expected_family = "main_league"
        expected_version = f"{folder.name}-v0.6.4-explainable"
    else:
        expected_family = NEW_CANDIDATE_FAMILIES[folder.name]
        expected_version = f"{folder.name}-v0.6.4-offline-candidate"
    if data.get("model_family") != expected_family:
        raise ValueError(f"{folder.name}: expected model_family {expected_family}")
    if str(data.get("model_version") or "") != expected_version:
        raise ValueError(f"{folder.name}: unexpected model_version")
    if folder.name in NEW_CANDIDATE_FAMILIES:
        metadata = folder / "model_metadata_v064.json"
        if not metadata.is_file() or not json.loads(metadata.read_text(encoding="utf-8")).get("sklearn_training_version"):
            raise ValueError(f"{folder.name}: missing candidate training version metadata")
    columns = folder / str(data.get("feature_columns_file") or "feature_columns.json")
    if not columns.is_file():
        raise ValueError(f"{folder.name}: missing feature columns")
    mapping = data.get("models") or {}
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError(f"{folder.name}: missing model mapping")
    for name in mapping.values():
        value = str(name)
        if Path(value).name != value or not (folder / value).is_file():
            raise ValueError(f"{folder.name}: missing/unsafe model artifact: {value}")


def install_missing_models(archive_path: Path, root: Path | None = None) -> dict:
    """Unzip on persistent disk without deserialising any sklearn models.

    Validation happens in a staging directory. Existing folders cannot be overwritten.
    """
    target = Path(root) if root is not None else model_root_path()
    target.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    seen: set[str] = set()
    with tempfile.TemporaryDirectory(prefix=".prix-model-stage-", dir=target) as tmp:
        stage = Path(tmp)
        try:
            with zipfile.ZipFile(archive_path) as zf:
                entries = zf.infolist()
                if len(entries) > MAX_ARCHIVE_FILES:
                    raise ValueError("Archive has too many entries")
                expanded = sum(item.file_size for item in entries)
                if expanded > MAX_EXPANDED_BYTES:
                    raise ValueError("Archive expands beyond the size limit")
                if not entries:
                    raise ValueError("Empty model archive")
                folder_names: set[str] = set()
                for item in entries:
                    name = item.filename.replace("\\", "/")
                    parts = PurePosixPath(name).parts
                    if (not parts or name.startswith("/") or ".." in parts or
                            item.flag_bits & 0x1 or _is_symlink(item)):
                        raise ValueError(f"Unsafe archive entry: {name}")
                    # The normal training ZIP stores model folders under
                    # models/<slug>. A small set of root report files is ignored.
                    # Only explicitly allowlisted model directories are installed.
                    if len(parts) == 1 and item.is_dir() and parts[0] == "models":
                        continue
                    if len(parts) == 1 and not item.is_dir() and parts[0] in {
                        "TRAINING_AND_VALIDATION_REPORT.md", "evaluation_summary.csv",
                        "evaluation_summary.json", "holdout_market_thresholds.csv",
                        "training_manifest.json", "smoke_test.json",
                        "staging_registry_candidates.json",
                    }:
                        continue
                    model_parts = parts[1:] if parts[0] == "models" else parts
                    folder = model_parts[0] if model_parts else ""
                    if folder not in ALLOWED_MISSING_FOLDERS or len(model_parts) < 2:
                        raise ValueError(f"Unexpected archive entry: {name}")
                    folder_names.add(folder)
                    if item.is_dir():
                        continue
                    if name in seen:
                        raise ValueError(f"Duplicate archive entry: {name}")
                    seen.add(name)
                    final = stage.joinpath(*model_parts)
                    final.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(item, "r") as reader, final.open("wb") as writer:
                        shutil.copyfileobj(reader, writer, length=1024*1024)
            for folder in folder_names:
                _check_model(stage / folder)
            for folder in sorted(folder_names):
                if (target / folder).exists():
                    raise ValueError(f"Model folder already exists (will not overwrite): {folder}")
            try:
                for folder in sorted(folder_names):
                    os.rename(stage / folder, target / folder)
                    installed.append(folder)
            except Exception:
                for folder in installed:
                    shutil.rmtree(target / folder, ignore_errors=True)
                raise
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid ZIP archive") from exc
    return {"ok": True, "installed_folders": installed,
            "installed_count": len(installed),
            "model_root": str(target),
            "next_step": "Reload the installed league registry and validate with /registry/diagnostics"}
