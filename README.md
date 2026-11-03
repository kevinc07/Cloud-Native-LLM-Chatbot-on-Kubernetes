# Cloud-Native LLM Chatbot on Kubernetes

一個跑在 Azure AKS 上的 LLM 聊天服務(FastAPI + LangChain + Gemini),重點不在聊天本身,而在**把它當成正式服務來運維**:
GitOps 自動發版、SLO 與告警、無狀態水平擴充、快取降級、可重現的故障演練。

## 這個專案實際做到什麼

| 主題 | 做到的事 | 證據 |
|---|---|---|
| **GitOps 發版** | push → GitLab CI(test → build arm64 image → release 把新 tag 寫回 git)→ ArgoCD 自動部署;測試失敗會擋住發版 | [docs/e2e-results.md](docs/e2e-results.md):連續 3 次無人工介入上線,部署期間 0 個非 200;故意壞測試 338 秒內沒有 release |
| **無狀態 + 快取** | 對話記憶存 MongoDB(source of truth),Redis 做 cache-aside;任一 replica 都能接續同一段對話 | [docs/day9-memory-bug.md](docs/day9-memory-bug.md)(修之前的錯亂)、`scripts/memory_test.py`(修之後歷史每輪 +2) |
| **SLO 與告警** | 可用性 99%、延遲 95% < 12s;多時間窗 burn-rate 告警;token 成本暴增告警 | [docs/SLO.md](docs/SLO.md)、`mychart/templates/prometheusrule.yaml` |
| **資源與擴縮** | requests/limits、HPA(1–5)、readiness/liveness probe、preStop 優雅下線 | `mychart/templates/backend-deployment.yaml` |
| **設定自動化** | Ansible 驗證輸入後改 values.yaml 的 ConfigMap 設定,走 git 讓 ArgoCD 部署 | [ansible/README.md](ansible/README.md) |

## 架構

```
                       ┌──────────────── GitLab ────────────────┐
  git push ──────────► │ test(pytest, helm lint)               │
                       │  → build(arm64 image → Container Reg.) │
                       │  → release(把 SHA tag 寫回 values.yaml)│
                       └──────────────────┬─────────────────────┘
                                          │ git 變更
                                          ▼
                                   ArgoCD(auto-sync, prune, selfHeal)
                                          │ helm render + apply
 ┌────────────────────────── AKS ─────────▼──────────────────────────┐
 │                                                                    │
 │  Ingress(nginx)                                                   │
 │   ├─ chatbot.local      → frontend(nginx + React, 2 replicas)     │
 │   └─ api.chatbot.local  → backend(FastAPI, HPA 1–5)               │
 │                              │            │            │           │
 │                              ▼            ▼            ▼           │
 │                           MongoDB      Redis       Gemini API      │
 │                       (source of truth) (快取,可丟) (外部)         │
 │                                                                    │
 │  Prometheus ◄── /metrics(ServiceMonitor)   Grafana(dashboard)    │
 │  Alertmanager ◄── PrometheusRule(SLO burn-rate、token 成本)       │
 └────────────────────────────────────────────────────────────────────┘
```

### 一次 `/chat` 請求

1. Ingress 把請求分給任一 backend replica(replica 之間沒有共享記憶體)。
2. `get_history`:先查 Redis → miss 就從 Mongo 讀最近 20 則並回填 → Redis 掛了就直讀 Mongo。
3. 帶著歷史呼叫 Gemini(`max_output_tokens` 限制單次成本)。
4. 先寫 Mongo,成功後才更新 Redis。Mongo 寫失敗回 503;Gemini 失敗回 502(兩者在指標上可分辨)。
5. 回應帶 `X-Served-By` / `X-History-Len`,用來驗證「換 pod 後歷史沒掉」。

## 目錄

| 路徑 | 內容 |
|---|---|
| `chatbot-backend/` | FastAPI 服務、`chat_store.py`(Mongo+Redis)、`metrics.py`、`tests/`(21 個測試) |
| `chatbot-frontend/` | React 前端 + nginx |
| `mychart/` | Helm chart:Deployment、HPA、Redis、Mongo、Ingress、ServiceMonitor、PrometheusRule、Grafana dashboard |
| `argocd/` | ArgoCD 安裝 values 與 Application |
| `.gitlab-ci.yml` | test → build → release |
| `ansible/` | ConfigMap 設定更新 playbook |
| `monitoring/` | kube-prometheus-stack 安裝與 dashboard 產生器 |
| `scripts/` | `memory_test.py`(多 replica 記憶一致性)、`load.sh`(負載) |
| `docs/` | SLO、端到端驗證、設計取捨與已知限制、各階段圖解 PDF |

## 本機執行

```bash
cd chatbot-backend
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -v            # 不需要 Gemini key、Mongo、Redis(用 fakeredis 與假 collection)
```

```bash
# 本機體驗前後端(需要 chatbot-backend/.env,內含 GOOGLE_API_KEY;不要進 git)
docker compose up --build      # 前端 :3000,後端 :8000
```

注意:`docker-compose.yml` 是早期的本機開發用,**沒有 Redis,也沒有把 backend 接上 Mongo**,
後端會退回程序內的 dict(只供開發)。要驗證 Mongo+Redis 與多 replica 行為,請用 AKS。

## 部署到 AKS(摘要)

Secret 都由人手動建立、**不進 git**:`chatbot-secret`(Gemini key)、`mongo-secret`、`langsmith-secret`、
`gitlab-registry`(拉 image 的 deploy token)。GitLab 專案需要 CI 變數 `CI_PUSH_TOKEN`(Maintainer、`write_repository`、masked)。

```bash
helm install argocd argo/argo-cd -n argocd --create-namespace -f argocd/values.yaml
kubectl apply -f argocd/application.yaml     # 之後所有變更都走 git
```

之後的日常流程只有 `git push`。

## 設計取捨與已知限制

寫在 [docs/design.md](docs/design.md):為什麼這樣選、哪些刻意沒做、哪些是還沒做的缺口。
面試時被問到「這個有什麼問題」,答案在那裡。
