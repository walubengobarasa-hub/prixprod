# Prix Model API — low-memory patch (2026-11-01)

## Scope
Targeted updates for `appapi.zip`, meant to overlay an EXISTING running FastAPI project, not replace its model or registry directories. No model weights, prediction thresholds, response schemas, fixture IDs, or ticket rules are changed.

Files to copy into the project root (overwriting only these four paths):
- `app/config.py`: default cache for **one** league model, bounded heavy-request wait.
- `app/model_registry.py`: evict previous model **before** deserialising next model, then reclaim references.
- `app/storage.py`: stream JSON cache writes to unique atomic files; load cached JSON with `json.load`; read-time parsing still needs memory for the full payload.
- `app/main.py`: only one memory-intensive request at a time, cheap cache metadata inspection, single-pass match normalisation, RSS and request-duration logs.

## Render configuration
Use **one server worker**. For example, if your current launch is Uvicorn, configure:

```
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1
```

Modify your existing Start Command only if the above matches your deployment/runtime. `WEB_CONCURRENCY=1` by itself will not override an explicit higher worker count.

Set on Render > Environment:

```
PRIX_MAX_CACHED_LEAGUE_MODELS=1
PRIX_HEAVY_REQUEST_WAIT_SECONDS=3
WEB_CONCURRENCY=1
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

The environment variable `PRIX_MAX_CACHED_LEAGUE_MODELS` overrides the code default: remove any old value of 3 or update it to 1. Configure BLAS/thread variables before importing NumPy / scikit-learn (the environment screen and restart handle this).

## Concurrency and failure handling
Heavy endpoints (predict, league sync, feature generation, fixture results, `/models`) are serialized **within one process**; requests that cannot acquire the gate within 3 seconds return HTTP 503 with `Retry-After: 5` and `code=MODEL_BUSY`. This protects memory, but is not a work queue. Keep ONE Uvicorn/Gunicorn worker and ONE Laravel ticket generation at a time. Health checks remain immediately available.

The gateway logs `heavy_request_start`, `heavy_request_end` with RSS MB + seconds, and `heavy_request_busy`. Check Render's memory chart because this patch does not guarantee any single league model bundle fits the instance.

## Deployment
1. Back up deployed source/config. Do not delete `models/`, your configured `leagues.json`, or persistent data/cache.
2. Copy the four patch files to the same `app/` paths in your FastAPI project.
3. Set the Render variables and one-worker start command; redeploy.
4. Check `/health` (must return HTTP 200) and model metadata, then request ONE league / ONE date before full generation.
5. Monitor RSS at start/end in Render logs and memory chart. If one league alone still exceeds memory, review that model's artifact sizes / replace unusually large models without blind automatic retries.

## Validation
Python syntax compilation and five smoke tests completed in the patch workspace. End-to-end testing with the deployed model artifacts, real FootyStats traffic and Render's RAM cap remains required.
