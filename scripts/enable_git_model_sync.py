"""Idempotent migration helper for repos using the previous Git sync entrypoint.

Current bundled app/main.py is already integrated; this tool is only for merges.
"""
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
path = root / 'app' / 'main.py'
if not path.is_file():
    sys.exit('Expected app/main.py in repository')
src = path.read_text(encoding='utf-8')
old = 'from app.git_model_sync import sync_git_models\n_PRIX_GIT_SYNC_STATUS = sync_git_models()'
new = 'from app.github_model_release import sync_render_models\n_PRIX_GIT_SYNC_STATUS = sync_render_models()'
if old in src:
    src = src.replace(old, new, 1)
elif new not in src:
    anchor = 'from app.league_registry import league_registry'
    if anchor not in src:
        sys.exit('Could not find registry anchor to integrate safely')
    src = src.replace(anchor, '# Synchronize GitHub Release models before registry loads\n' + new + '\n' + anchor, 1)
status_route = '@app.get("/registry/git-sync-status", dependencies=[Depends(require_api_key)])'
if status_route not in src:
    anchor = '@app.get("/registry/status", dependencies=[Depends(require_api_key)])'
    if anchor not in src:
        sys.exit('Could not find status endpoint anchor; no changes written')
    src = src.replace(anchor, status_route + '\ndef git_sync_status():\n    return _PRIX_GIT_SYNC_STATUS\n\n\n' + anchor, 1)
path.write_text(src, encoding='utf-8')
print('GitHub Release sync integration present in app/main.py')
