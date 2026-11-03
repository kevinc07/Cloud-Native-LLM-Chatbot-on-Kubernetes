# Day 9 證據:多 replica 下記憶體版對話記憶不一致

環境:AKS,backend 由 HPA 從 1 個擴到 5 個 pod(2026-10-29)。

## HPA 擴容事件
```
  Normal   SuccessfulRescale             3m6s                  horizontal-pod-autoscaler  New size: 4; reason: cpu resource utilization (percentage of request) above target
  Normal   SuccessfulRescale             2m51s                 horizontal-pod-autoscaler  New size: 5; reason: cpu resource utilization (percentage of request) above target
```

## 同一段對話連打 10 輪(scripts/memory_test.py)
expected = 這段對話應累積的歷史則數;seen = 該 pod 實際看到的則數。
```
turn  expected  seen  pod
   1         0     0  chatbot-backend-85b9cd7487-hr97s
   2         2     0  chatbot-backend-85b9cd7487-wcq6c   <-- 記憶不一致!
   3         4     0  chatbot-backend-85b9cd7487-gvgkh   <-- 記憶不一致!
   4         6     0  chatbot-backend-85b9cd7487-k4lbk   <-- 記憶不一致!
   5         8     2  chatbot-backend-85b9cd7487-hr97s   <-- 記憶不一致!
   6        10     2  chatbot-backend-85b9cd7487-gvgkh   <-- 記憶不一致!
   7        12     0  chatbot-backend-85b9cd7487-7lj8m   <-- 記憶不一致!
   8        14     2  chatbot-backend-85b9cd7487-wcq6c   <-- 記憶不一致!
   9        16     2  chatbot-backend-85b9cd7487-k4lbk   <-- 記憶不一致!
  10        18     2  chatbot-backend-85b9cd7487-7lj8m   <-- 記憶不一致!
```

結論:每輪被 Ingress 分到不同 pod,而對話記憶存在各 pod 自己的記憶體,所以歷史時有時無。Mongo 其實有完整紀錄,但目前只寫不讀。Day 20 改成 Mongo + Redis cache-aside 修復。

備註:第 11 輪起 Gemini 免費額度(20 requests)用完,回 429,後端目前把它當 500 回傳。
