# Model release deployment

Laravel can deploy validated model ZIPs to this API through the authenticated `/admin/releases/deploy` endpoint.

For Render persistence, mount a persistent disk and set:

- `MODEL_ROOT=/var/data/prix-models`
- `MODEL_RELEASE_ROOT=/var/data/prix-model-releases`

The service keeps release snapshots for rollback. Without persistent storage, runtime deployments can be lost when Render restarts or redeploys.
