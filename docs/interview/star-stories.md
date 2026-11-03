# STAR Stories

Seven stories from this project, written for behavioural and project deep-dive interviews.
Every number comes from a measurement in this repo. Each story ends with the honest limitation,
because the follow-up question "what would you do differently?" is almost guaranteed.

Tip: tell each story in about 2 minutes. Situation + Task in 2–3 sentences, most of the time on Action, and end with a number.

---

## 1. Conversation memory broke when the service scaled out
**Maps to:** stateless service, MongoDB + Redis cache-aside, multi-replica verification

- **Situation:** The chatbot kept conversation history in each pod's memory. That worked with one replica. When I load-tested and the HPA scaled the backend to 5 pods, users lost context mid-conversation.
- **Task:** Prove the bug, then make the service truly stateless without slowing it down.
- **Action:**
  - I added two debug headers, `X-Served-By` (which pod answered) and `X-History-Len` (how much history it saw), and wrote `scripts/memory_test.py` to replay one conversation and compare expected vs. actual history on every turn.
  - The evidence was clear: on turn 10 the conversation should have had 18 messages; the answering pod saw 2.
  - I made MongoDB the single source of truth and added Redis as a cache-aside layer: read Redis, fall back to MongoDB on a miss and refill, and fall back to MongoDB if Redis is down. Writes go to MongoDB first and only then update Redis, using a `WATCH`/`MULTI` transaction.
  - I wrote unit tests with fakeredis for hit, miss, Redis-down and write-failure paths.
- **Result:** After the fix, history grew by exactly 2 per turn no matter which pod answered. In the later Redis outage drill, all 15 requests during the outage returned 200 with full history.
- **Limitation / what I'd do next:** Concurrent requests on the same conversation are not locked, and a Redis outage costs ~1 s per request because there's no circuit breaker.

## 2. Getting deployments to zero errors
**Maps to:** readiness/liveness probes, graceful shutdown, end-to-end GitOps verification

- **Situation:** The GitOps pipeline worked, but a script polling the service during each rollout saw 502 errors on every deploy.
- **Task:** Make every deploy invisible to users, and prove it over several runs, not just once.
- **Action:**
  - First cause: no readiness probe. Kubernetes marked the container Ready as soon as it started, before uvicorn was listening. I added readiness and liveness probes on `/health`.
  - 502s still appeared occasionally. I worked out the second cause: when a pod is deleted, removing it from the Service endpoints and sending SIGTERM happen at the same time, so the ingress can still route to a dying pod. I added a `preStop: sleep 5` hook so the pod keeps serving while the endpoint removal propagates.
  - I defined success as three consecutive clean end-to-end runs with no manual steps.
- **Result:** Runs 7, 8 and 9 each had **0 non-200 responses** during rollout; push-to-live time was about 5 minutes (CI ≈ 162 s).
- **Limitation:** No staging environment, post-deploy smoke test or automatic rollback. ArgoCD guarantees "cluster equals git", not "the app is correct".

## 3. A retry storm hidden inside an SDK
**Maps to:** fault-injection drill, SLO and cost alerts, capped retries with backoff

- **Situation:** While preparing a failure drill, I checked what our LLM client actually does when Gemini fails. The LangChain Gemini client defaulted to `max_retries=6` and **no timeout**.
- **Task:** Show the real impact, then fix it with something measurable.
- **Action:**
  - I built a fake LLM with injectable delay, error rate and timeout, so drills cost no API quota.
  - I reproduced the default behaviour under load: 6 concurrent clients against an LLM that always fails after 3 s.
  - I moved retries out of the SDK into our own policy: per-call timeout of 20 s, at most 2 attempts, exponential backoff with jitter, a 30 s overall deadline, and no retry on 429 (quota exhausted).
  - I added a metric for every attempt, `llm_attempts_total`, and an alert when attempts per request exceed 1.5.
- **Result:** LLM calls per request dropped from **7.0 to 2.0**, and time to fail dropped from **47.7 s to 6.5 s**. In a hang scenario the request now fails in 10.6 s instead of waiting indefinitely. The new alert and the SLO fast-burn alerts fired during the storm.
- **Limitation:** 2× is still amplification during a full outage. The next step is a circuit breaker. I also note the measurement caveat: my load clients were closed-loop, so per-request amplification is the right metric, not total call rate.

## 4. Setting an SLO from data instead of a template
**Maps to:** latency SLO, multi-window burn-rate alerts, token-cost alert

- **Situation:** The project plan suggested "95% of requests under 3 seconds".
- **Task:** Set SLOs that would actually be useful for paging.
- **Action:**
  - I measured first. `/chat` p95 was about **9.75 s**, with ~7.85 s inside the Gemini call. Most output tokens were reasoning tokens. A 3 s target would have paged constantly.
  - I set `/chat` to 95% under 12 s, and kept a strict 200 ms target for `/health`, which doesn't call the LLM. I aligned 12 s with a histogram bucket boundary so the PromQL is exact rather than interpolated.
  - I used multi-window burn-rate alerts (14.4× over 1h AND 5m; 6× over 6h AND 30m) with a minimum-traffic guard.
  - For cost, I alert on tokens/hour vs. a baseline. I found that a mean baseline was inflated by a single spike for ~23 hours (threshold rose from 20k to 85k), so I switched to a median and excluded the most recent hour.
- **Result:** Alerts that fire on real budget burn and not on noise, all verified by fault injection with the fake LLM.
- **Limitation:** Prometheus keeps only 2 days without a PVC, so there is no true 30-day budget view, and Alertmanager has no receiver yet.

## 5. Making "a failing test blocks the release" true, and proving it
**Maps to:** GitLab CI + ArgoCD GitOps pipeline

- **Situation:** I wanted fully automatic delivery: push code, and the new version reaches AKS with no manual steps, but never a broken build.
- **Task:** Design the pipeline and prove the safety property.
- **Action:**
  - Three stages: `test` (pytest + helm lint/template) → `build` (arm64 images, because the AKS node is ARM; my first deploy failed with `exec format error`) → `release`, which commits the new SHA tag to `values.yaml` with `[skip ci]` to avoid an infinite loop.
  - CI never touches the cluster. ArgoCD (auto-sync, prune, selfHeal) pulls from git, so CI needs no cluster credentials.
  - SHA tags instead of `latest`, because ArgoCD only reacts to a git change and SHA tags make every deploy traceable and revertible.
  - To prove the safety property, I pushed a test that always fails.
- **Result:** After 338 s, double the normal release time, there was no release commit and the cluster stayed on the previous version. Removing the test released and deployed normally.
- **Limitation:** Two pushes close together can race in the release stage. GitLab `resource_group` would serialise it.

## 6. A one-line environment variable that crashed the backend
**Maps to:** Kubernetes debugging

- **Situation:** After adding a Redis Service called `redis`, the backend started crash-looping.
- **Task:** Find out why a working container broke without any code change.
- **Action:** The startup traceback was a `ValueError` from `int(os.getenv("REDIS_PORT"))`. Kubernetes injects legacy Docker-link environment variables for every Service in the namespace, so a Service named `redis` produced `REDIS_PORT=tcp://10.x.x.x:6379`, which collided with my app's own `REDIS_PORT` setting. I set `enableServiceLinks: false` on the pod spec and kept configuration explicit in the ConfigMap.
- **Result:** The backend started cleanly, and the fix applies to any future Service name collision.
- **Lesson:** Platform defaults (like the SDK retry defaults in story 3) are worth reading before they surprise you.

## 7. GitOps vs. manual changes: where selfHeal stops
**Maps to:** Ansible ConfigMap automation, ArgoCD

- **Situation:** I needed a safe way to change runtime configuration. With ArgoCD selfHeal on, any manual `kubectl edit` gets reverted.
- **Task:** Automate config changes without fighting GitOps.
- **Action:** I wrote an Ansible playbook that validates the input, edits the `config:` values in git, runs `helm lint` and `helm template`, and optionally commits and pushes. ArgoCD then rolls it out. The playbook is idempotent (a second run reports `changed=0`) and supports `--check --diff` previews.
  During the incident drill I found the edge of selfHeal: it reverted changed values, but it did **not** remove keys I had added by hand to the ConfigMap. I cleaned them up explicitly and documented it.
- **Result:** Config changes flow through review and git history, and I learned exactly what "self-healing" does and does not guarantee.
- **Limitation:** The playbook runs against localhost only; there's no remote inventory.

---

## Quick map: resume bullet → story

| Resume bullet | Stories |
|---|---|
| Latency SLOs, burn-rate + token-cost alerts, fault-injection drill | 3, 4 |
| Helm deployment with requests/limits and HPA | 1, 2 |
| Stateless service, MongoDB source of truth + Redis cache-aside, verified with multiple replicas | 1, 6 |
| GitOps pipeline (GitLab CI + ArgoCD) that blocks releases on failing tests | 2, 5 |
| Ansible-automated ConfigMap updates | 7 |
