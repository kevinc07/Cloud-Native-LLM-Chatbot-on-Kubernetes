# Mock Interview Question Bank

Questions an interviewer is likely to ask about this project, with a short model answer and the follow-up to expect.
Answers are grounded in what this repo actually does. Practise them out loud, and keep each answer under about 90 seconds.

## 0. The 60-second pitch

> "I built an LLM chatbot, FastAPI with Gemini, and focused on running it like a production service on Azure Kubernetes.
> Code ships through GitOps: GitLab CI tests and builds arm64 images, then writes the new image tag back to git, and ArgoCD deploys it.
> A failing test blocks the release, and I verified that. Deploys are zero-downtime: three consecutive runs with no non-200 responses, after I fixed probes and graceful shutdown.
> The service is stateless. History lives in MongoDB with a Redis cache, and I proved it with a multi-replica test that reproduced the original bug.
> I set SLOs from measured latency, 95% under 12 seconds, with multi-window burn-rate alerts and a token-cost alert.
> Then I ran failure drills. One found that the Gemini SDK retried up to 6 times with no timeout. Capping retries cut LLM calls per failing request from 7 to 2 and time-to-fail from 48 to 6.5 seconds."

---

## 1. Kubernetes

**Q: Why do you need both a readiness and a liveness probe?**
Readiness decides whether a pod gets traffic; liveness decides whether it gets restarted. Without readiness, my pods got traffic before uvicorn was listening, which showed up as 502s during deploys. Liveness catches a hung process. They answer different questions, so a failing readiness check should not kill the pod.
*Follow-up:* "What could go wrong with liveness?" A liveness check that depends on a downstream service (like MongoDB) can restart every pod during that dependency's outage. Mine only checks the process via `/health`.

**Q: Probes were in place but you still saw 502s. Why?**
On pod deletion, endpoint removal and SIGTERM happen in parallel. The ingress may still route to the pod for a moment after it starts shutting down. `preStop: sleep 5` keeps it serving while the endpoint change propagates. After that I had 0 errors across three deploys.

**Q: How does your HPA work, and what limits it?**
It targets 50% CPU of the request, 1 to 5 replicas. The real limit is the single B2ps_v2 node: CPU requests were at about 97% of allocatable, so a third replica stayed Pending. In production I'd add a node pool with the cluster autoscaler, and probably scale on request rate or latency rather than CPU, since `/chat` mostly waits on I/O.
*Follow-up:* "Why is CPU a poor signal here?" The backend spends most of its time waiting on Gemini, so CPU stays low even when it's saturated with concurrent requests.

**Q: How do requests and limits affect scheduling?**
The scheduler places pods by requests, not actual usage. Limits cap usage: exceeding the CPU limit throttles, exceeding the memory limit gets the container OOM-killed. I sized requests from observed usage and kept memory limits a few times above normal usage.

**Q: Tell me about a Kubernetes surprise.**
Service links. Kubernetes injected `REDIS_PORT=tcp://...` because my Service was named `redis`, which overwrote my app's `REDIS_PORT` and crashed it at startup. I fixed it with `enableServiceLinks: false`.

## 2. CI/CD and GitOps

**Q: Walk me through what happens when you push.**
GitLab CI runs pytest and helm lint/template. If they pass, it builds arm64 images and pushes them tagged with the short commit SHA. The release job commits that tag to `values.yaml` with `[skip ci]`. ArgoCD sees the git change, renders the Helm chart and applies it. In total, about 5 minutes from push to live.

**Q: Why GitOps instead of `kubectl apply` or `helm upgrade` from CI?**
CI never needs cluster credentials. Git is the audit log and the rollback mechanism. selfHeal reverts drift. The cost is an extra commit per release and some latency.

**Q: Why not use `latest`?**
ArgoCD only reacts to changes in git, so with `latest` nothing changes and nothing deploys. And `latest` doesn't tell you which code is running. A SHA tag is traceable and a revert is a rollback.

**Q: How do you know a failing test really blocks the release?**
I tested it. I pushed a test that always fails; after 338 seconds, double the normal time, there was no release commit and the cluster stayed on the old version.

**Q: What's broken about your pipeline?**
Two pushes close together can race in the release stage and write an older tag; `resource_group` would fix it. There's no staging, smoke test or automatic rollback. I'd add a post-sync smoke test and Argo Rollouts for canary analysis.

**Q: How would you roll back?**
`git revert` the release commit; ArgoCD deploys the previous tag. Images are immutable and tagged by SHA, so the old image is still in the registry.

## 3. Observability and SLOs

**Q: How did you choose your SLOs?**
From measurements. `/chat` p95 was ~9.75 s, mostly Gemini reasoning, so I set 95% under 12 s. `/health` doesn't call the LLM, so it gets 99% under 200 ms. Availability is 99% non-5xx.

**Q: Explain burn rate and why you alert on two windows.**
Burn rate is the error rate divided by the error budget; 1 means the budget runs out exactly at the end of the window. I page when burn rate exceeds 14.4 over both 1 hour and 5 minutes. The long window proves the problem is significant; the short window proves it's still happening, so the alert also clears quickly after recovery.
*Follow-up:* "Where does 14.4 come from?" 14.4× for one hour consumes 2% of a 30-day budget. It's from the Google SRE Workbook.

**Q: How do you monitor cost?**
I count input and output tokens from the model response's usage metadata. An alert fires when tokens in the last hour exceed 3× the median of the previous 23 hours, with an absolute floor. I chose the median because a single spike inflated a mean baseline for almost a day.

**Q: What can't your monitoring do?**
Prometheus keeps 2 days without a persistent volume, so there's no 30-day budget view, and Alertmanager isn't routed to Slack or a pager. The cost number is an estimate from tokens, not the bill.

## 4. Data, caching and state

**Q: Why cache-aside and not write-through or read-through?**
The cache is optional: if Redis disappears the service still works. Writes go to MongoDB first and only update Redis after that succeeds, so the source of truth never lags the cache. Misses and outages fall back to MongoDB.

**Q: What happens if the MongoDB write succeeds but the Redis update fails?**
I try to delete the key so the next read rebuilds it from MongoDB, and the TTL is the last safety net. The Redis update uses `WATCH`/`MULTI`, so a concurrent change makes the transaction retry instead of overwriting.

**Q: How do you handle cache invalidation and consistency?**
Writes update or invalidate the key; keys have a 30-minute TTL; the model always receives the last 20 messages whether the cache hits or misses, so the cache affects latency, never the answer. A known gap: two concurrent requests on the same conversation aren't locked.

**Q: Why not a LangGraph checkpointer?**
I only need "send the last N messages". No branching, tool loops or human-in-the-loop. A checkpointer would add a state format and migrations without adding a feature.

**Q: What happens when Redis goes down?**
I tested it: 15 requests during the outage, all 200, history intact. But each request paid about 1 extra second waiting for the Redis timeout. A circuit breaker would skip Redis after a few consecutive failures.

## 5. LLM-specific

**Q: How do you handle LLM failures?**
Per-call timeout of 20 s; at most 2 attempts with exponential backoff and jitter; a 30 s overall deadline; no retry on 429. LLM failures return 502, distinct from 503 for database failures. Every attempt is counted, and an alert fires if attempts per request exceed 1.5.

**Q: Why not just keep the SDK's retries?**
They were invisible and unbounded in time: 6 retries and no timeout. In the drill that meant 7 calls per failing request and 48 seconds to fail.

**Q: How do you test LLM behaviour without spending money?**
A fake LLM with the same interface, with injectable delay, error rate, timeout and token counts. It drove the SLO alert tests and the retry drill. Unit tests use a stub. The trade-off: real model behaviour is only checked manually.

**Q: How do you control cost per request?**
History is truncated to 20 messages and `max_output_tokens` is 2048, which includes reasoning tokens. On top of that, per-IP rate limiting at the ingress and the token-spike alert.

## 6. Security (expect to be challenged)

**Q: How do users authenticate?**
They don't, really. The user ID is a name sent in a header. That was a deliberate scope decision for a demo focused on operations. Every endpoint gets identity through one function, `current_user()`, so replacing it with JWT or OAuth is a single change. Ownership checks stop someone with just a conversation ID, but not someone typing another user's name.

**Q: What else would you fix before production?**
TLS (it's plain HTTP on an sslip.io hostname); a NetworkPolicy for `/metrics` inside the cluster; managed secrets (External Secrets or Sealed Secrets) instead of manual `kubectl create`; and masking or disabling prompt tracing to LangSmith.

## 7. System design extensions

**Q: How would you take this to 10,000 concurrent users?**
Multiple nodes and the cluster autoscaler; scale on concurrency or latency instead of CPU; streaming responses; a managed, replicated MongoDB and Redis; a queue or semaphore around LLM calls to respect provider rate limits; a circuit breaker; and per-user quotas in addition to per-IP limits. Make the provider pluggable, so traffic can fail over to a second model.

**Q: How would you do multi-region?**
Stateless backends in each region, a globally replicated database with conversation affinity, and per-region caches that can be lost. GitOps makes it easy: one ArgoCD Application per cluster, or an ApplicationSet.

## 8. Behavioural

**Q: Tell me about a time you were wrong.**
My cost alert originally used the mean as the baseline. Data showed one spike raised the threshold from 20k to 85k tokens per hour for about a day, which could hide a second incident. I switched to the median and documented that even the median fails with very short history.

**Q: Tell me about a time you found a problem nobody asked you to look for.**
The SDK retry defaults (story 3), or the selfHeal limitation found during the drill (story 7).

**Q: What are you most proud of in this project?**
Every claim has a measurement behind it, including the failures: zero-error deploys took 9 runs, and the doc explains why the first 6 failed.

---

## How to run a mock interview

1. Pick 5 questions across sections 1–6 and one from section 7. Answer out loud and time yourself.
2. After each answer, have the interviewer ask "why?" twice. The second "why" is where the trade-offs and limitations come in.
3. Finish with one behavioural question answered as a STAR story from [star-stories.md](star-stories.md).
