"""Convert only Git-tracked Prix deployment text artifacts to LF (never models).

Usage:
  python scripts/normalize_deploy_text.py         # dry run
  python scripts/normalize_deploy_text.py --apply # normalize in place

Does not modify .pkl/.joblib, the manifest, other repositories, or Render.
After applying, regenerate the manifest with prepare_github_models.py --write.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "deploy_models"


def targets():
    registry = BASE / "leagues.json"
    if registry.is_file():
        yield registry
    models = BASE / "models"
    if models.is_dir():
        for file in sorted(models.rglob("*")):
            if file.is_file() and not file.is_symlink() and file.suffix.lower() in {".csv", ".json"}:
                yield file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Convert CRLF to LF in CSV/JSON files")
    args = parser.parse_args()
    changed = 0
    scanned = 0
    for file in targets():
        scanned += 1
        original = file.read_bytes()
        updated = original.replace(b"\r\n", b"\n")
        if updated != original:
            changed += 1
            print(f"{'Normalized' if args.apply else 'Would normalize'}: {file.relative_to(ROOT).as_posix()}")
            if args.apply:
                file.write_bytes(updated)
    print(f"Scanned {scanned} text files; {'normalized' if args.apply else 'requiring normalization'}: {changed}")
    print("Model binaries (.pkl/.joblib) and model_manifest.json were not changed.")


if __name__ == "__main__":
    main()
