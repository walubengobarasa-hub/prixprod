"""Read-only check: run from repository root as `python verify_route.py`."""
from app.main import app
expected = {"/admin/models/replace-seven-1-6-1", "/admin/models/rollback-seven-1-6-1"}
paths = {r.path for r in app.routes}
missing = sorted(expected - paths)
if missing:
    raise SystemExit("MISSING endpoint(s): " + ", ".join(missing))
for path in sorted(expected):
    print("REGISTERED:", path)
print("Use GET /openapi.json on live Render to verify it loaded the deployed version.")
