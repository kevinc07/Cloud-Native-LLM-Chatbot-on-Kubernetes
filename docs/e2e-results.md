# Day 22–24 端到端驗證紀錄

流程:改 code → `git push` → GitLab CI(test → build arm64 image → release 把新 tag 寫回 values.yaml)→ ArgoCD 偵測 git 變更並部署 → 驗證。全程無手動 kubectl / helm。

## Day 23:連續 3 次成功(第 7–9 輪)

| 輪次 | CI 耗時 | 全程耗時 | 部署過程中非 200 次數 | 結尾 `/health` | `/chat` |
|---|---|---|---|---|---|
| 7 | 162s | 294s | 0 | 200 | OK |
| 8 | 162s | 296s | 0 | 200 | OK |
| 9 | 162s | 354s | 0 | 200 | OK |

CI 耗時 = push 到 CI 把新 tag 寫回 git 的時間。全程耗時 = push 到新版本在 cluster 上就緒。

### 前 6 輪為什麼不算通過(都是真問題)
| 現象 | 原因 | 修法 |
|---|---|---|
| 部署後立刻打 `/health` 得 502 | backend/frontend 沒有 readiness probe,容器一啟動就被當 Ready,uvicorn 還沒監聽 | 加 readiness + liveness probe |
| 加 probe 後仍偶爾 502(第 4、5 輪) | Pod 被刪時,「移出 Service/Ingress 名單」與「SIGTERM」同時發生,ingress 仍把請求送給正在關閉的 Pod | 加 `preStop: sleep 5` 優雅下線 |
| 前 3 輪 push 全被拒 | 測試腳本 `git pull` 預設拉 GitHub(origin),CI 的 release commit 只在 GitLab | 明確 `git pull --rebase gitlab main` |

## Day 24:壞測試擋住發版

故意 push 一個必定失敗的測試(`61ab3dbf`):
- 等了 338 秒(正常 release 約 160 秒內出現),**沒有** `release 61ab3dbf` commit。
- cluster 上的版本維持 `d452fc30`,Pod 沒有被替換。
- 移除壞測試後(`cc37a119`),release 與部署恢復正常。

原因:`release` 階段排在 `test`、`build` 之後,前一階段任何 job 失敗,後面階段不會執行;tag 沒被寫回 git,ArgoCD 就沒有新東西可部署。

## 已知限制
- 兩次 push 靠很近時,兩個 pipeline 的 release 階段可能競爭,後完成的可能把 tag 蓋回舊版本。可用 GitLab `resource_group` 把 release 串行化(尚未做)。
- 沒有 staging 環境,也沒有部署後的自動 smoke test / 自動回滾;ArgoCD 只保證 cluster 與 git 一致,不保證應用正確。
- 驗證靠「git 裡出現 release commit」與 cluster 狀態判斷,無法在這裡直接查看 GitLab pipeline 畫面。
