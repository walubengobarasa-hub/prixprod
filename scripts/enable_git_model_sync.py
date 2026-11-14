"""Apply additive, idempotent integration to the CURRENT FastAPI app/main.py.

Never replaces main.py; preserves existing routes and release-specific patches.
"""
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parent.parent
main = root / "app" / "main.py"
if not main.exists():
    sys.exit(f"Cannot find {main}; place this patch in your FastAPI repository root")
src = main.read_text(encoding="utf-8")
anchor = "from app.league_registry import league_registry"
insertion = (
    "# Populate the persistent model root from Git BEFORE LeagueRegistry is loaded.\n"
    "from app.git_model_sync import sync_git_models\n"
    "_PRIX_GIT_SYNC_STATUS = sync_git_models()\n"
)
status_anchor = '@app.get("/registry/status", dependencies=[Depends(require_api_key)])'
status_insertion = (
    '@app.get("/registry/git-sync-status", dependencies=[Depends(require_api_key)])\n'
    'def git_sync_status() -> dict[str, Any]:\n'
    '    """Result of automatic Git model sync during this process startup."""\n'
    '    return _PRIX_GIT_SYNC_STATUS\n\n\n'
)
if anchor not in src or status_anchor not in src:
    sys.exit("Expected integration anchor(s) not found. App unchanged; merge manually.")
updated = src
if insertion not in updated:
    updated = updated.replace(anchor, insertion + anchor, 1)
if status_insertion not in updated:
    updated = updated.replace(status_anchor, status_insertion + status_anchor, 1)
if updated != src:
    backup = main.with_suffix('.py.before-git-sync')
    if not backup.exists():
        shutil.copy2(main, backup)
    main.write_text(updated, encoding="utf-8")
    print(f"Integrated Git model sync into {main} (original saved to {backup.name})")
else:
    print("Git model sync already integrated — no changes")
