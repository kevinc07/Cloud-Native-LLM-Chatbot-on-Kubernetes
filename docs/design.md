# 設計取捨與已知限制

## 一、設計取捨(為什麼這樣選)

### 1. 對話記憶:Mongo 當真相、Redis 當快取,不用 LangGraph checkpointer
- **問題**:最初記憶放各 pod 的記憶體,HPA 擴到多個 replica 後歷史時有時無([day9-memory-bug.md](day9-memory-bug.md))。
- **選擇**:Mongo 為唯一 source of truth;Redis cache-aside 只降低讀取延遲。Redis 丟了可由 Mongo 重建,所以 Redis 不開持久化、設 `maxmemory` + LRU + TTL。
- **為什麼不用 LangGraph checkpointer**:這個服務只有「送最近 N 則歷史給模型」一種需求,沒有分支、人工介入、工具迴圈。引進 checkpointer 會多一層狀態格式與遷移成本,卻換不到功能。
- **為什麼不用 Gemini Interactions API(伺服器端保存對話)**:狀態放在供應商那邊,換模型就丟記憶、無法自己做保留期與刪除,也讓 Mongo 不再是唯一真相。
- **寫入順序**:先 Mongo、後 Redis。Mongo 失敗就回 503、快取不動——寧可使用者重送,也不要「看到回覆但紀錄沒存」。
- **送給模型的永遠是最近 N 則(預設 20)**,不論快取命中與否,所以快取只影響延遲、不影響答案。

### 2. 三層「快取/節流」各管一件事
| 層 | 目的 |
|---|---|
| Redis cache-aside | 降低讀取歷史的延遲與 Mongo 負載 |
| 歷史截斷(N 則)+ `max_output_tokens` | 限制單次請求成本的上限 |
| Gemini implicit caching(只觀測) | 長 prompt 才會命中(門檻數千 token),短對話通常為 0;只量測、不優化 |

### 3. GitOps:CI 不碰 cluster,只改 git
- CI 只負責把「剛建好的 image SHA tag」寫回 `values.yaml`,部署由 ArgoCD 拉取。CI 不需要 cluster 憑證,攻擊面小。
- **用 SHA tag 而非 `latest`**:ArgoCD 只看 git,tag 不變就沒東西可部署;SHA 也能追溯是哪個 commit、回滾就是 revert 一個 commit。
- **release commit 帶 `[skip ci]`**:否則改 tag 的 commit 會再觸發 pipeline,無限循環。
- **擋住壞版本靠 stage 順序**:test 失敗 → build/release 不執行 → 沒有新 tag → ArgoCD 沒東西可部署。實測見 [e2e-results.md](e2e-results.md)。
- **開 selfHeal**:手動改 cluster 會被改回 git 的樣子,所以 Ansible 改的是 git 而不是 cluster。

### 4. SLO 數字來自量測,不照搬
`/chat` 延遲 SLO 是 12 秒而不是常見的 3 秒:實測 p95 ≈ 9.75 秒(Gemini reasoning 佔大宗)。照搬 3 秒只會讓告警永遠響。`/health` 不呼叫 LLM,才訂 200ms。詳見 [SLO.md](SLO.md)。

### 5. 告警用 burn rate + 雙窗
固定門檻不隨 SLO 鬆緊改變;burn rate 直接代表「預算還能撐多久」。長窗證明問題夠大、短窗證明還在發生,兩者同時成立才告警。

### 6. 刻意把 502 與 503 分開
502 = Gemini 失敗(外部依賴),503 = Mongo 不可用(自己的依賴)。兩者都算進可用性 SLI,但排查路徑不同,指標與日誌可區分。

### 7. LLM 呼叫:逾時與重試自己管
SDK 預設重試 6 次、無逾時,出事時會把流量放大 7 倍且看不見。改成 SDK 不重試、自管最多 2 次 + 退避 + 期限,並以 `llm_attempts_total` 觀測放大倍數。演練與數字見 [incident-drill.md](incident-drill.md)。

### 8. 優雅下線要兩個機制一起
實測部署時出現 502:Pod 被刪時「移出 Endpoints」與「SIGTERM」同時發生,ingress 仍把請求送給正在關閉的 Pod。解法是 readiness probe(避免太早接流量)+ `preStop: sleep 5`(留時間讓 Endpoints 傳播)。修好後連續 3 次部署 0 個非 200。

## 二、已知限制(誠實列出)

### 發版流程
- **release 階段有競爭**:兩次 push 靠很近時,兩個 pipeline 的 release 可能交錯,後完成的把 tag 蓋回舊版。對策:GitLab `resource_group` 串行化(尚未做)。
- **沒有 staging、沒有部署後 smoke test、沒有自動回滾**。ArgoCD 只保證「cluster = git」,不保證應用正確。回滾目前是手動 revert。
- 無法在本環境直接查看 GitLab pipeline 畫面;驗證靠 release commit 與 cluster 狀態。

### 容量與可用性
- **單節點 AKS(B2ps_v2)**:node CPU requests 已逼近上限,第三個 backend replica 會 Pending——HPA 設 max 5 在這個節點上實際到不了。節點掛了整個服務停擺。
- **MongoDB、Redis 都是單一實例**:沒有複寫、沒有備份策略。Redis 掛了會降級(變慢但可用);Mongo 掛了 `/chat` 回 503。
- **Redis 掛掉時每個請求多等約 1 秒**(逾時後才降級直讀 Mongo),沒有 circuit breaker;LLM 重試也只是封住上限(2 倍),同樣沒有 circuit breaker([incident-drill.md](incident-drill.md))。
- 同一段對話的**併發請求沒有加鎖**,極端情況下 Redis 與 Mongo 的順序可能暫時不一致(TTL 到期後自癒)。

### 安全
- **沒有真正的使用者驗證**:`user_id` 由前端送來、後端直接信任,任何人可冒用。
- **`/metrics` 經 ingress 公開可達**,應限制在叢集內或加 NetworkPolicy。
- **LangSmith 會收到 prompt 內容**:不適合處理敏感資料,正式環境需要遮罩或關閉。
- Secret 由人手動 `kubectl create`,沒有 Sealed Secrets / External Secrets 之類的管理。

### 觀測與成本
- **看不到 30 天 SLO 窗口**:Prometheus 只留 2 天、沒掛 PVC,cluster 重啟歷史就清空。
- **Alertmanager 沒有接收端**(Slack / PagerDuty / Email)。
- **成本是 token 估算,不是帳單**;dashboard 的單價是可調的占位值。
- 成本告警的基準在歷史很短時意義有限,主要靠絕對下限兜底(詳見 SLO.md)。

### 測試
- 單元/整合測試用 fakeredis 與假 collection,**沒有對真 Mongo/Redis 的整合測試**;多 replica 一致性靠 `scripts/memory_test.py` 在 cluster 上驗證,不在 CI 裡。
- 根目錄 `docker-compose.yml` 是早期本機開發用,沒有 Redis、backend 也沒接 Mongo,不能代表正式堆疊。
- Gemini 呼叫用假 LLM 取代,真實模型行為(逾時、429)只在手動演練中驗證。
