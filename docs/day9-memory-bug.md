# Evidence: in-memory conversation history breaks with multiple replicas

Environment: AKS, backend scaled by the HPA from 1 to 5 pods (2026-10-29).

## HPA scale-up events
```
  Normal   SuccessfulRescale   3m6s    horizontal-pod-autoscaler  New size: 4; reason: cpu resource utilization (percentage of request) above target
  Normal   SuccessfulRescale   2m51s   horizontal-pod-autoscaler  New size: 5; reason: cpu resource utilization (percentage of request) above target
```

## One conversation, 10 turns (`scripts/memory_test.py`)
`expected` = how many history messages the conversation should have; `seen` = how many the answering pod actually had.
```
turn  expected  seen  pod
   1         0     0  chatbot-backend-85b9cd7487-hr97s
   2         2     0  chatbot-backend-85b9cd7487-wcq6c   <-- inconsistent
   3         4     0  chatbot-backend-85b9cd7487-gvgkh   <-- inconsistent
   4         6     0  chatbot-backend-85b9cd7487-k4lbk   <-- inconsistent
   5         8     2  chatbot-backend-85b9cd7487-hr97s   <-- inconsistent
   6        10     2  chatbot-backend-85b9cd7487-gvgkh   <-- inconsistent
   7        12     0  chatbot-backend-85b9cd7487-7lj8m   <-- inconsistent
   8        14     2  chatbot-backend-85b9cd7487-wcq6c   <-- inconsistent
   9        16     2  chatbot-backend-85b9cd7487-k4lbk   <-- inconsistent
  10        18     2  chatbot-backend-85b9cd7487-7lj8m   <-- inconsistent
```

Conclusion: the ingress sent each turn to a different pod, and history lived in each pod's own memory, so it came and went.
MongoDB had the full record, but the code only wrote to it and never read from it. The fix was MongoDB as the source of truth
plus a Redis cache-aside layer; after it, `X-History-Len` grows by 2 every turn no matter which pod answers.

Note: from turn 11 the Gemini free-tier quota (20 requests) ran out and returned 429, which the backend then surfaced as 500.
(It now returns 502 for LLM failures and does not retry 429.)
