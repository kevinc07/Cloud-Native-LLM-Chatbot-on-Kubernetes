# 操作速查表

每個 `port-forward` 要各開一個終端機分頁(指令會卡住,正常);關分頁就斷線。
`kubectl` 回 `no such host` = AKS 是停止的,先啟動。

## AKS 開關
```bash
az aks start -g rg-chatbot-dev -n aks-chatbot-dev      # 開(約 5 分鐘才 Ready)
az aks stop  -g rg-chatbot-dev -n aks-chatbot-dev      # 關(不用時一定要關,開著會計費)
az aks show  -g rg-chatbot-dev -n aks-chatbot-dev --query powerState.code -o tsv
kubectl get nodes                                       # Ready 才算起來
```

## 對外網址
`http://chat.172-184-203-57.sslip.io`(Ingress 公網 IP 是 `172.184.203.57`;IP 變了要改 `values.yaml` 的 `ingress.host`)

## 看狀態
```bash
kubectl get pods                       # 應用本體
kubectl get pods -A | grep -E "argocd|monitoring"
kubectl logs deploy/chatbot-backend    # backend log
kubectl get hpa                        # 自動擴縮
kubectl get ing                        # Ingress
```

## 監控三件套(都只在叢集內,用 port-forward 看)
| 工具 | 指令 | 網址 | 帳密 |
|---|---|---|---|
| Grafana | `kubectl -n monitoring port-forward svc/monitoring-grafana 3001:80` | http://localhost:3001 | `admin` / 見下 |
| Prometheus | `kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090` | http://localhost:9090 | 無 |
| Alertmanager | `kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-alertmanager 9093:9093` | http://localhost:9093 | 無 |
| ArgoCD | `kubectl -n argocd port-forward svc/argocd-server 8080:443` | **https**://localhost:8080(憑證警告選繼續) | `admin` / 見下 |

```bash
# Grafana 密碼
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d; echo
# ArgoCD 初始密碼(若 not found,代表被刪或改過)
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
```

- Grafana:Dashboards → **Chatbot Overview**(最上方是 SLO,下面有快取命中率)。
- Prometheus:Alerts 看告警;Graph 輸入 `llm_attempts_total` 等指標。
- ArgoCD:`chatbot` 應為 **Synced / Healthy**。

## LangSmith(看每次 LLM 呼叫的 prompt、回應、token)
LangSmith 是 LangChain 官方的雲端服務,**不在叢集裡**,不用 port-forward。
1. 瀏覽器開 https://smith.langchain.com 登入(建立 API key 的那個帳號)。
2. 左側 Tracing / Projects → 找專案 **`chatbot-aks`**(`values.yaml` 的 `langsmith.project`)。
3. 每次呼叫 `/chat` 都會出現一筆 trace,點進去可看 prompt、回覆、延遲、token。

運作方式:backend 有 `LANGSMITH_TRACING=true` 與 `LANGSMITH_API_KEY`(來自 Secret `langsmith-secret`),
LangChain 看到就自動上傳,不用改程式。注意 **prompt 內容會送到 LangSmith**(見 design.md 的安全限制)。
關閉:把 `values.yaml` 的 `langsmith.enabled` 改成 `false` 並 push。

## 發版(日常只有 git)
```bash
git push gitlab main && git push origin main     # 兩個 remote 都推
git pull --rebase gitlab main                     # CI 會寫 release commit 回 GitLab,pull 要用 gitlab
```
CI:test → build → release;ArgoCD 約 3–5 分鐘後部署。docs-only 的 commit 訊息加 `[skip ci]` 可略過 CI。

## 本機測試
```bash
cd chatbot-backend && ../venv/bin/python -m pytest -q     # 28 個測試,不需要 Gemini / Mongo / Redis
helm lint mychart && helm template c mychart > /dev/null   # chart 檢查
```

## 故障演練(Day 27)
詳見 [incident-drill.md](incident-drill.md)。演練會暫停 ArgoCD 同步、手動改 ConfigMap,**結束後要:**
1. 恢復自動同步:`kubectl -n argocd patch app chatbot --type merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'`
2. selfHeal 不會刪掉手動多加的 key(例如 `FAKE_LLM_*`),要用 `kubectl patch cm chatbot-config --type merge -p '{"data":{"KEY":null}}'` 明確刪除,再 `kubectl rollout restart deploy/chatbot-backend`。

## 叢集層級、不在 git 裡的手動設定
- `ingress-nginx` Service 設為 `externalTrafficPolicy: Local`(讓限流看得到真實來源 IP)。
- 各種 Secret:`chatbot-secret`、`mongo-secret`、`langsmith-secret`、`grafana-admin`、`gitlab-registry`。
