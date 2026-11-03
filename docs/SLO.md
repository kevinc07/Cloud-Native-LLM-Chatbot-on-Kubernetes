# Service Level Objectives

## Terms

| Term | Meaning | Example |
|---|---|---|
| **SLI** (Service Level Indicator) | What we actually measure | "0.4% of `/chat` requests failed in the last hour" |
| **SLO** (Service Level Objective) | The target we set for ourselves | "99% of `/chat` requests succeed" |
| **Error budget** | Allowed failure = 1 − SLO | 99% → 1% |
| **Burn rate** | How fast the budget is spent = observed error rate ÷ error budget | 1 = budget runs out exactly at the end of the window; 14.4 = 14.4× faster |

An SLA is a contractual promise to customers with penalties. An SLO is an internal target, usually stricter. This project only has SLOs.

## The SLOs

| Service | SLI | SLO | Error budget |
|---|---|---|---|
| `/chat` availability | Share of requests that are not 5xx | **99%** | 1% |
| `/chat` latency | Share of requests finished within **12 s** | **95%** | 5% |
| `/health` latency | Share of requests finished within **200 ms** | **99%** | 1% |
| LLM cost (guardrail, not an SLO) | Tokens used in the last hour | < max(3 × baseline, 20,000), baseline = median | — |

### Why 12 seconds for `/chat`, not 3

`/chat` calls Gemini, and most of the time is spent in the model. Measured with `gemini-3.6-flash` at the default
`medium` thinking level: **p95 ≈ 9.75 s** for `/chat`, of which the Gemini call was ≈ 7.85 s. Replies were only a few dozen
words, but output tokens were 290–430, of which 270–390 were reasoning tokens. A "95% under 3 s" target cannot be met with
this model configuration and would only produce an alert that never stops. SLOs should come from measurements: measure first, then set the target.

`/health` does not call the LLM, so a strict 200 ms target makes sense there. Setting them separately is more honest.

> If `thinking_level` is lowered to `low`/`minimal`, re-measure and tighten the `/chat` latency SLO.
> When the threshold changes, `slo.chat.latencyThreshold` in `values.yaml` must match a histogram bucket boundary (see `metrics.py`).

## Alerting: multi-window burn rate

| Alert | Condition (long window AND short window) | For | Severity |
|---|---|---|---|
| `ChatAvailabilityFastBurn` / `ChatLatencyFastBurn` | burn rate > **14.4** (1h AND 5m) | 2m | page |
| `ChatAvailabilitySlowBurn` / `ChatLatencySlowBurn` | burn rate > **6** (6h AND 30m) | 15m | ticket |
| `LLMRetryAmplification` | average LLM calls per `/chat` > 1.5 (5m window) | 3m | page |
| `LLMTokenUsageSpike` | tokens in last 1h > max(3 × median of the previous 23h, 20,000) | 5m | ticket |

- **Why burn rate instead of "error rate > X%"?** A fixed threshold ignores how strict the SLO is. Burn rate maps directly to
  "how long until the budget is gone", and the alerts follow automatically when the SLO changes.
- **Why two windows?** A short window alone pages on brief blips. A long window alone detects slowly and keeps firing after recovery.
  The long window proves the problem is large; the short window proves it is still happening.
- **Where do 14.4 and 6 come from?** The Google SRE Workbook: 14.4× for 1 hour burns 2% of a 30-day budget; 6× for 6 hours burns 5%.
- **Low-traffic guard:** no alert when there were fewer than 10 requests in the hour (1 failure in 3 requests is 33%, which is noise).
- **Cost-alert baseline: the median hourly usage of the previous 23 hours, excluding the most recent hour.**
  Excluding the last hour stops a spike from raising its own baseline and hiding itself.
  The median rather than the mean: once a spike leaves the last hour it enters the 23-hour window, and a mean would stay inflated for
  about 23 hours. In one measurement a single ~650k-token spike raised the threshold from 20k to 85k, so a second spike in that period might not alert.
  The median is insensitive to outliers. With no history the baseline is 0 and the absolute floor (20,000 tokens/h) takes over.

Rule definitions: [`mychart/templates/prometheusrule.yaml`](../mychart/templates/prometheusrule.yaml).
All thresholds live under `slo:` in [`mychart/values.yaml`](../mychart/values.yaml).

## Known limitations

- **No 30-day view.** Prometheus keeps only 2 days of data and has no disk, so the project uses burn-rate alerts (short windows)
  and cannot show "how much of the 30-day budget is left". Production would need longer retention (or Thanos / Mimir) and a PVC.
- **Alertmanager has no receiver.** Alerts are visible in the Prometheus / Alertmanager UI but are not routed to Slack, PagerDuty or email.
- **The latency SLI includes fast failures.** 5xx responses are usually quick and count as "fast". Availability and latency are independent SLIs, each with its own budget.
- **The cost baseline needs enough normal history.** With very short history, or history filled by one spike, the median is dominated by the spike too
  (measured: about 2 hours after a drill the baseline was ~640k and the threshold ~1.9M, worse than the mean). Since Prometheus has no disk and
  loses history on every cluster restart, in this environment the alert mostly works through its absolute floor (20,000 tokens/h).
  Production fix: a PVC, longer retention, and possibly a cap on the baseline.
- **Cost is a token-based estimate, not the actual bill.**
