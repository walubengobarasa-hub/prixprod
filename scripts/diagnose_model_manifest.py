"""Explain why the committed model_manifest.json fails the existing --check.

Use locally or in GitHub Actions after `git lfs pull`:
  python scripts/diagnose_model_manifest.py
Prints up to 12 mismatches, never changes model files or the manifest.
"""
from __future__ import annotations

import json
from pathlib import Path
from prepare_github_models import prepare, BASE


def main():
    manifest_file = BASE / "model_manifest.json"
    if not manifest_file.is_file():
        print("MISSING: deploy_models/model_manifest.json")
        return
    try:
        saved = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"INVALID manifest JSON: {exc}")
        return
    try:
        actual = prepare()
    except (ValueError, OSError) as exc:
        print(f"MODEL VALIDATION FAILED before manifest comparison: {exc}")
        return
    if saved.get("registry_sha256") != actual["registry_sha256"]:
        print("REGISTRY SHA MISMATCH: deploy_models/leagues.json")
        print("  committed:", saved.get("registry_sha256"))
        print("  actual:   ", actual["registry_sha256"])
    for key in ("folders", "format"):
        if saved.get(key) != actual.get(key):
            print(f"{key.upper()} MISMATCH: committed={saved.get(key)!r} actual={actual.get(key)!r}")
    past = saved.get("files", {})
    if not isinstance(past, dict):
        print("INVALID manifest: files is not a dictionary")
        return
    fresh = actual["files"]
    different = [(path, past.get(path), fresh.get(path)) for path in sorted(set(past) | set(fresh)) if past.get(path) != fresh.get(path)]
    if different:
        print(f"FILE ENTRY MISMATCHES: {len(different)} / {len(fresh)}")
        for path, expected, got in different[:12]:
            if expected is None:
                kind = "unexpected in checkout"
            elif got is None:
                kind = "missing in checkout"
            else:
                kind = "content/size mismatch"
            print(" ", kind, path)
            if expected is not None:
                print("    committed", expected)
            if got is not None:
                print("    actual   ", got)
    if not different and saved.get("registry_sha256") == actual["registry_sha256"] and saved.get("folders") == actual["folders"] and saved.get("format") == actual["format"]:
        print("Manifest matches semantically. If --check fails, inspect JSON formatting/newlines.")
    else:
        print("Fix the reported source differences; do NOT regenerate the manifest in GitHub Actions.")


if __name__ == "__main__":
    main()
