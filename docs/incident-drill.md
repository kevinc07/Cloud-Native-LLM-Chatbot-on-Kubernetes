# Incident Drill and Postmortem

Two drills, both run on AKS (2026-11-02). Faults were injected with a fake LLM (`FakeLLM`), so **no Gemini quota was used**.
That also means "token cost" can only be estimated from call counts, not from a bill.

## Drill 1: the LLM keeps failing → retry storm

### Cause (found, not guessed)
`langchain-google-genai` defaults to `max_retries=6` and `timeout=None` (confirmed by reading the client's `model_fields`). So:
when Gemini errors, **every `/chat` silently makes up to 7 calls inside the SDK**; when Gemini hangs, a call **may never time out**.
Retries exist to absorb brief blips, but against a dependency that is already unhealthy they multiply traffic. And because they happen inside the SDK, none of them showed up in our metrics.

### Method
- Fault: every LLM call fails after 3 s (`FAKE_LLM_ERROR_RATE=1`, simulating a 503).
- Load: 6 concurrent clients, each sending `/chat` back-to-back.
- **A (old behaviour reproduced):** the same code configured to mimic the SDK defaults: up to 7 attempts, backoff 1 → 10 s, no deadline. This reproduces the behaviour through configuration; it is not the old binary. The backoff curve is my assumption; **the 7 attempts** come from the SDK default.
- **B (after the fix):** at most 2 attempts, backoff 0.5 → 4 s, 30 s deadline, 20 s per-call timeout.

### Results
| | A: SDK defaults | B: capped retries |
|---|---|---|
| Completed requests | 30 (all 502) | 114 (all 502) |
| Average time per request | **47.7 s** (max 52 s) | **6.5 s** (max 6.6 s) |
| LLM calls per request (`llm_attempts_total` ÷ `/chat` requests) | **7.0** | **2.0** |
| Alerts | `LLMRetryAmplification`, `ChatAvailabilityFastBurn`, `ChatLatencyFastBurn` fired | — (config switched after the drill; did not wait for alerts again) |

Two things to read carefully:
1. **Look at amplification per request, not the total call rate.** My clients were closed-loop: each waited for a response before sending the next.
   Because B failed fast, its clients sent more often, so B's total call rate (~2/s) was actually higher than A's (~1.1/s).
   Real users arrive at their own pace and do not slow down because the server is slow, so A's 7× would multiply real traffic.
2. **B is still 2×.** When the dependency is fully down, retries still add load; the fix only caps it. A circuit breaker
   (stop calling for a while after repeated failures) would be the complete answer. **Not done.**

### Second scenario: the upstream hangs
With a 30 s injected delay and a 5 s per-call timeout, the request ended with 502 in **10.6 s** (5 s + 0.4 s backoff + 5 s) instead of hanging 30 s or more.
The old default `timeout=None` has no such protection, so slow calls would keep holding worker threads.

### Timeline (observed during the drill)
1. Fault injected, load started → each request took ~48 s to fail.
2. `LLMRetryAmplification` fired after the amplification stayed at 7.0 (> 1.5) for 3 minutes; the availability and latency fast-burn alerts fired too.
3. Switched to the capped config → time per request fell from 48 s to 6.5 s and amplification to 2.0.

### Root cause and fix
| | |
|---|---|
| Root cause | Relying on SDK defaults: 6 retries, no timeout, and retries invisible to us |
| Fix | `llm_client.py`: SDK retries off, 20 s per-call timeout; our own retry policy (max 2 attempts, exponential backoff + jitter, 30 s overall deadline, no retry on 429) |
| Observability | New metric `llm_attempts_total{result}`; new alert `LLMRetryAmplification` (> 1.5 calls per request for 3 minutes) |
| Regression guard | 7 unit tests (attempt cap, backoff growth and cap, deadline, no retry on 429, metric counting) |

### Trade-offs
- **Why 2 attempts, not 1:** it absorbs a single transient failure while capping amplification at 2×. One attempt is safest but gives up the benefit of retrying.
- **Why no retry on 429:** when the quota is exhausted, retrying only hits the wall faster.
- **Jitter:** when several replicas fail at the same moment, they do not all retry at the same moment.

## Drill 2: Redis goes down

### Method
One conversation, 36 turns in a row (LLM healthy, no delay). At turn 11 Redis was scaled to 0; at turn 26 it was restored.

### Results
| Phase | Result | `/chat` time | Conversation history |
|---|---|---|---|
| Redis up (turns 1–10) | 200 | ~0.06 s | +2 per turn |
| **Redis down (turns 11–25)** | **all 200, zero errors** | **~1.06 s** | intact (capped at 20, served from MongoDB) |
| Redis back (turn 26 on) | 200 | ~0.06 s (cache refilled automatically) | intact |

`cache_requests_total{result="error"}` rose during the outage and is visible on the dashboard's cache panel.

### Problem found
The degradation worked (no outage, no lost memory), but **every request paid about 1 extra second**, waiting for the Redis timeout before reading MongoDB.
With no circuit breaker, every request pays that cost again for as long as Redis is down. It barely affects the 12 s latency SLO, but under heavy traffic that second ties up workers.
**Not fixed**; listed in [design.md](design.md). A likely fix: after N consecutive failures, skip Redis for a short period.

## Notes on running the drill
- To edit the ConfigMap for the drill, ArgoCD auto-sync was paused and re-enabled afterwards.
- **Surprise:** after re-enabling, selfHeal did **not** remove the `FAKE_LLM_*` keys I had added by hand. ArgoCD manages the fields that exist in git and ignores extra keys.
  I deleted them explicitly with `kubectl patch`, restarted the backend, and confirmed `FAKE_LLM=False`.
  **This is a real limit of selfHeal:** it reverts changed values, but it does not guarantee that added fields are removed.
