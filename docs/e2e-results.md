# End-to-End Delivery Results

Flow: change code → `git push` → GitLab CI (test → build arm64 image → release writes the new tag back to `values.yaml`) →
ArgoCD detects the git change and deploys → verify. No manual `kubectl` or `helm` at any step.

## Three consecutive successful deploys (runs 7–9)

| Run | CI time | Total time | Non-200 responses during rollout | Final `/health` | `/chat` |
|---|---|---|---|---|---|
| 7 | 162 s | 294 s | 0 | 200 | OK |
| 8 | 162 s | 296 s | 0 | 200 | OK |
| 9 | 162 s | 354 s | 0 | 200 | OK |

CI time = from push until CI commits the new tag to git. Total time = from push until the new version is ready on the cluster.
A script polled the service throughout each rollout and counted every non-200 response.

### Why runs 1–6 did not count (each one found a real problem)
| Symptom | Cause | Fix |
|---|---|---|
| `/health` returned 502 right after a deploy | No readiness probe on backend/frontend. A container counted as Ready the moment it started, before uvicorn was listening. | Added readiness and liveness probes |
| Occasional 502 even with probes (runs 4–5) | On pod deletion, "removed from Service endpoints" and SIGTERM happen at the same time, so the ingress still routed requests to a pod that was shutting down | Added `preStop: sleep 5` for graceful shutdown |
| All pushes rejected in runs 1–3 | The test script's `git pull` pulled from GitHub (`origin`), but CI's release commits only exist on GitLab | Pull explicitly with `git pull --rebase gitlab main` |

## A failing test blocks the release

A deliberately failing test was pushed (`61ab3dbf`):
- After 338 s (a normal release commit appears within ~160 s) there was **no** `release 61ab3dbf` commit.
- The cluster stayed on `d452fc30`; no pods were replaced.
- After removing the test (`cc37a119`), release and deploy resumed normally.

Why: `release` runs after `test` and `build`. If any job in an earlier stage fails, later stages do not run. No tag is written to git, so ArgoCD has nothing new to deploy.

## Known limitations
- If two pushes land close together, their release jobs can race and the later one may write an older tag back. GitLab `resource_group` would serialise them (not done).
- No staging environment, no post-deploy smoke test, no automatic rollback. ArgoCD only guarantees the cluster matches git, not that the app is correct.
- Verification used the release commits in git and the cluster state, not the GitLab pipeline UI.
