# SLO 文件

## 名詞

| 名詞 | 意思 | 例子 |
|---|---|---|
| **SLI**(Service Level Indicator) | 實際量到的數字 | 「過去 1 小時 /chat 有 0.4% 的請求失敗」 |
| **SLO**(Service Level Objective) | 對自己訂的目標 | 「99% 的 /chat 請求要成功」 |
| **Error budget** | 允許失敗的額度 = 1 − SLO | 99% → 1% |
| **Burn rate** | 預算消耗速度 = 實際失敗率 ÷ error budget | 1 = 剛好在窗口結束時花完;14.4 = 快 14.4 倍 |

SLA 是對客戶的合約承諾(違反要賠錢);SLO 是內部目標,通常比 SLA 嚴。本專案只有 SLO。

## 本專案的 SLO

| 服務 | SLI | SLO | Error budget |
|---|---|---|---|
| `/chat` 成功率 | 非 5xx 的請求比例 | **99%** | 1% |
| `/chat` 延遲 | 在 **12 秒**內完成的請求比例 | **95%** | 5% |
| `/health` 延遲 | 在 **200ms** 內完成的請求比例 | **99%** | 1% |
| LLM 成本(護欄,非 SLO) | 近 1 小時 token 用量 | < max(3 × 基準, 20,000)(基準=中位數) | — |

### 為什麼 `/chat` 是 12 秒,不是 3 秒

`/chat` 要呼叫外部 Gemini,大部分時間花在模型端。Day 12 實測 `gemini-3.6-flash`(預設 `medium` 思考量)
的 `/chat` **p95 ≈ 9.75 秒**,其中 Gemini 呼叫 ≈ 7.85 秒;回覆只有幾十字,但 output token 約 290–430,
其中 reasoning(思考)佔 270–390。所以「95% < 3 秒」這種數字在這個模型設定下根本達不到,
照搬只會讓告警永遠響。SLO 應該建立在**量測**上:先量、再訂。

`/health` 不呼叫 LLM,才適合 200ms 這種嚴格標準。兩者分開訂比較誠實。

> 之後若把 `thinking_level` 調成 `low`/`minimal`,應重新量測並收緊 `/chat` 的延遲 SLO。
> 門檻改變時,`values.yaml` 的 `slo.chat.latencyThreshold` 必須同步成 histogram 的 bucket 邊界(見 `metrics.py`)。

## 告警設計:多時間窗 burn-rate

| 告警 | 條件(長窗 AND 短窗同時成立) | 持續 | 等級 |
|---|---|---|---|
| `ChatAvailabilityFastBurn` / `ChatLatencyFastBurn` | burn rate > **14.4**(1h 窗 AND 5m 窗) | 2m | page |
| `ChatAvailabilitySlowBurn` / `ChatLatencySlowBurn` | burn rate > **6**(6h 窗 AND 30m 窗) | 15m | ticket |
| `LLMRetryAmplification` | 平均每個 /chat 呼叫 LLM > 1.5 次(5m 窗) | 3m | page |
| `LLMTokenUsageSpike` | 近 1h token > max(3 × 前 23h 中位數, 20,000) | 5m | ticket |

- **為什麼是 burn rate,不是「失敗率 > X%」?** 固定門檻不管 SLO 鬆緊;burn rate 直接對應「預算還能撐多久」,
  SLO 改了告警自動跟著改。
- **為什麼要兩個窗?** 只看短窗會被瞬間抖動誤報;只看長窗發現得慢、恢復後還會繼續響。
  「長窗證明問題夠大,短窗證明它現在還在發生」。
- **14.4 與 6 哪來的?** Google SRE Workbook 的建議值:14.4× 持續 1 小時 = 燒掉 30 天預算的 2%;6× 持續 6 小時 = 5%。
- **流量過低的保護:** 1 小時內請求數 < 10 不告警(3 個請求錯 1 個 = 33%,是雜訊不是訊號)。
- **成本告警的基準:前 23 小時每小時用量的「中位數」,且排除最近 1 小時。**
  排除最近 1 小時:否則突波會把自己的基準墊高、蓋住自己。
  用中位數而非平均:突波滑出最近 1 小時後會進入「前 23 小時」,平均值會被單一突波墊高約 23 小時
  (實測:一次約 65 萬 token 的突波讓告警門檻從 2 萬升到 8.5 萬),期間第二次暴增可能不告警;中位數對極端值不敏感。
  沒有歷史資料時基準為 0,由絕對下限(20,000 token/h)兜底。

規則定義:[`mychart/templates/prometheusrule.yaml`](../mychart/templates/prometheusrule.yaml);
所有門檻集中在 [`mychart/values.yaml`](../mychart/values.yaml) 的 `slo:`。

## 已知限制(誠實列出)

- **看不到 30 天窗口。** Prometheus 資料只留 2 天且沒掛硬碟,所以只能做 burn-rate(短窗),
  無法顯示「30 天 error budget 還剩多少」。正式環境要加長保留(或 Thanos / Mimir)並掛 PVC。
- **Alertmanager 沒有接收端。** 告警會在 Prometheus / Alertmanager UI 看到,但沒有串 Slack / PagerDuty / Email。
- **延遲 SLI 包含快速失敗。** 5xx 的請求通常很快就回,會被算進「快」的那邊;成功率與延遲是兩條獨立的 SLI,各自守各自的預算。
- **成本基準需要足夠的正常歷史才有意義。** 基準取前 23 小時的中位數;歷史很短、或剛好被一次突波填滿時,
  中位數也會被突波主宰(實測:演練後約 2 小時歷史,基準變成約 64 萬,門檻升到約 190 萬,反而比平均更鈍)。
  Prometheus 沒掛硬碟、只留 2 天,每次 cluster 重啟歷史就清空,所以這條告警在演練環境裡主要靠絕對下限(20,000 token/h)運作。
  正式環境的對策:掛 PVC 與較長保留期,並可再加一個基準上限。
- **成本是 token 估算,不是實際帳單。**
