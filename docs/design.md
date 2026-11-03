# Design Trade-offs and Known Limitations

## Part 1 — Trade-offs (why it is built this way)

### 1. Conversation memory: MongoDB as source of truth, Redis as cache (no LangGraph checkpointer)
- **Problem:** History first lived in each pod's memory. Once the HPA scaled to several replicas, history appeared and disappeared depending on which pod answered ([day9-memory-bug.md](day9-memory-bug.md)).
- **Choice:** MongoDB is the single source of truth. Redis is a cache-aside layer that only reduces read latency. Redis can be rebuilt from MongoDB, so it runs without persistence, with `maxmemory`, LRU eviction and a TTL.
- **Why not a LangGraph checkpointer:** The service needs exactly one thing: send the last N messages to the model. There is no branching, no human-in-the-loop and no tool loop. A checkpointer would add a state format and migration cost without adding a feature.
- **Why not server-side conversation state from the model vendor:** The state would live with the provider. Switching models would lose memory, we could not control retention or deletion, and MongoDB would stop being the single source of truth.
- **Write order:** MongoDB first, then Redis. If MongoDB fails the request returns 503 and the cache is untouched. A user retrying is better than a user seeing an answer that was never saved.
- **The model always receives the last N messages (default 20)**, whether the cache hits or not. The cache changes latency, never the answer.

### 2. Three layers, each with one job
| Layer | Purpose |
|---|---|
| Redis cache-aside | Lower history-read latency and MongoDB load |
| History truncation (N messages) + `max_output_tokens` | Put an upper bound on the cost of a single request |
| Gemini implicit caching (observed only) | Only hits on long prompts (thousands of tokens), so it is usually 0 for short chats. Measured, not optimised. |

### 3. GitOps: CI never touches the cluster
- CI only writes the freshly built image SHA tag back to `values.yaml`. ArgoCD pulls the change and deploys it. CI holds no cluster credentials, which shrinks the attack surface.
- **SHA tags instead of `latest`:** ArgoCD only watches git, so an unchanged tag means nothing to deploy. A SHA tag also traces back to an exact commit, and a rollback is a single `git revert`.
- **Release commits carry `[skip ci]`.** Otherwise the tag-bump commit would trigger another pipeline, forever.
- **Bad builds are blocked by stage order:** a failing test means build and release never run, so no new tag is written and ArgoCD has nothing to deploy. Measured in [e2e-results.md](e2e-results.md).
- **selfHeal is on:** manual cluster edits are reverted to match git, so the Ansible playbook edits git, not the cluster.

### 4. SLO targets come from measurements
The `/chat` latency SLO is 12 s, not the common 3 s. Measured p95 was about 9.75 s, mostly Gemini reasoning time, so a 3 s target would page forever. `/health` does not call the LLM, so it gets a strict 200 ms target. Details in [SLO.md](SLO.md).

### 5. Burn-rate alerts over two windows
A fixed error-rate threshold ignores how strict the SLO is. Burn rate says directly how fast the error budget is being spent. The long window proves the problem is big enough; the short window proves it is still happening. Both must hold to alert.

### 6. 502 and 503 are deliberately different
502 means Gemini failed (external dependency). 503 means MongoDB is unavailable (our own dependency). Both count against the availability SLI, but they need different investigations, and metrics and logs keep them apart.

### 7. Identity check before the cache read
Redis keys are only the `conversation_id`. Reading the cache first would bypass authorization, so `/chat` asks MongoDB who owns the conversation before touching the cache. The upsert filter also includes `user_id`. If two users race to create the same new id, the loser hits the unique index (`DuplicateKeyError` → 404). The cost is one small indexed MongoDB lookup per request.

### 8. LLM calls: we own the timeout and the retries
The SDK defaults are 6 retries and no timeout. During an outage that silently multiplies traffic by 7. The SDK retry is now disabled and the service makes at most 2 attempts with backoff and an overall deadline. `llm_attempts_total` makes the amplification visible. Drill and numbers in [incident-drill.md](incident-drill.md).

### 9. Graceful shutdown needs two mechanisms
Deploys initially produced 502s. When a pod is deleted, removal from the Service endpoints and SIGTERM happen at the same time, so the ingress kept sending requests to a pod that was shutting down. The fix combines a readiness probe (no traffic before the app listens) with `preStop: sleep 5` (time for the endpoint removal to propagate). After the fix, 3 consecutive deploys had 0 non-200 responses.

## Part 2 — Known limitations (stated honestly)

### Release pipeline
- **The release stage can race.** If two pushes land close together, their release jobs can interleave and the later one may write an older tag. Fix: serialise with GitLab `resource_group` (not done).
- **No staging, no post-deploy smoke test, no automatic rollback.** ArgoCD guarantees "cluster equals git", not "the app is correct". Rollback today is a manual revert.
- Pipeline results were verified through the release commit and cluster state, not the GitLab UI.

### Capacity and availability
- **Single-node AKS (B2ps_v2).** Node CPU requests are near the limit, so a third backend replica stays Pending. The HPA max of 5 is not reachable on this node, and losing the node takes the whole service down.
- **MongoDB and Redis are single instances** with no replication and no backup policy. Losing Redis degrades the service (slower but working). Losing MongoDB makes `/chat` return 503.
- **During a Redis outage every request waits about 1 s** for the Redis timeout before falling back to MongoDB. There is no circuit breaker. LLM retries are capped at 2x but also have no circuit breaker ([incident-drill.md](incident-drill.md)).
- **"Stop" only works in the browser.** The browser stops waiting, but the backend Gemini call still finishes, the tokens are still spent, and the answer is still saved to MongoDB. True cancellation would need the backend to detect the disconnect and cancel the call (not done).
- The frontend does not render Markdown (it only handles code blocks), so Gemini's `**bold**` and list markers show as raw text.
- File upload in the "+" menu is placeholder UI. The backend does not accept files, so the frontend blocks sending with an attachment instead of silently dropping it. Search filters titles client-side (up to 50 conversations).
- **Concurrent requests on the same conversation are not locked.** In rare cases Redis and MongoDB ordering can differ briefly; the TTL heals it.

### Security
- **No real authentication.** Identity is a name the user types (`X-User-Id` header), with no password or signature, so anyone who types another person's name can read or delete their conversations. This is a deliberate scope decision: the project is about operations, not auth, and it is demo-only. Every endpoint gets identity only through `current_user()`, so moving to JWT/OAuth means changing that one function.
- **What the ownership check does stop:** knowing someone's `conversation_id` without their name gives 404 for read, write and delete. It does not leak whether the id exists, and the Redis cache cannot bypass it. It cannot stop name impersonation.
- **`/metrics` is no longer exposed through the ingress** (only `/chat`, `/conversations`, `/health` and the web UI are). It is still reachable inside the cluster; there is no NetworkPolicy yet.
- **Public traffic is plain HTTP** (free sslip.io hostname, no TLS). Rate-limited requests get 503 instead of 429 (changing that needs a global ingress-nginx setting outside this repo). Per-IP limits need the real client IP, which requires `externalTrafficPolicy: Local` on the ingress-nginx Service. That is a manual cluster setting, not in git.
- **LangSmith receives prompt contents**, so this setup is not suitable for sensitive data without masking or disabling tracing.
- Secrets are created by hand with `kubectl create`; there is no Sealed Secrets or External Secrets.

### Observability and cost
- **No 30-day SLO window.** Prometheus keeps 2 days of data with no PVC, and history is lost when the cluster restarts.
- **Alertmanager has no receiver** (no Slack, PagerDuty or email).
- **Cost is a token-based estimate, not the bill.** The dashboard prices are adjustable placeholders.
- The cost-alert baseline means little when history is short, so the alert mostly relies on its absolute floor (see [SLO.md](SLO.md)).

### Testing
- Unit and API tests use fakeredis and a fake collection. **There are no integration tests against real MongoDB or Redis.** Multi-replica consistency is verified on the cluster with `scripts/memory_test.py`, not in CI.
- The root `docker-compose.yml` is an early local setup with no Redis and no MongoDB connection, so it does not represent the real stack.
- Gemini is replaced by a fake LLM in tests. Real model behaviour (timeouts, 429) was only verified in manual drills.
