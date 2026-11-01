"""產生 mychart/dashboards/chatbot-overview.json(Grafana dashboard)。
用法:python3 monitoring/gen_dashboard.py
手寫大 JSON 容易出錯,所以用程式產生並把腳本一起版控。"""
import json

DS = {"type": "prometheus", "uid": "prometheus"}
panels = []
_id = [0]


def panel(title, kind, exprs, x, y, w, h, unit=None, desc=None, legend=None, decimals=None, thresholds=None):
    _id[0] += 1
    p = {
        "id": _id[0],
        "title": title,
        "type": kind,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [
            {"refId": chr(65 + i), "expr": e, "datasource": DS,
             **({"legendFormat": legend[i]} if legend else {}),
             **({"instant": True} if kind == "stat" else {})}
            for i, e in enumerate(exprs)
        ],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    if thresholds:
        # thresholds = [(起點值或 None, 顏色), ...]。None 代表從負無限大開始的底色。
        # 沒設的話 Grafana 預設「超過 80 才變紅」,對 0~1 的比例完全沒意義(SLI 0% 還是綠的)。
        p["fieldConfig"]["defaults"]["color"] = {"mode": "thresholds"}
        p["fieldConfig"]["defaults"]["thresholds"] = {
            "mode": "absolute",
            "steps": [{"color": c, "value": v} for v, c in thresholds],
        }
    if desc:
        p["description"] = desc
    if kind == "stat":
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "area"}
    return p


# 第一列:一眼看懂的數字
panels.append(panel(
    "/chat 請求量 (req/min)", "stat",
    ['sum(rate(http_requests_total{path="/chat"}[5m])) * 60'], 0, 0, 6, 4, unit="short", decimals=2))
panels.append(panel(
    "/chat 錯誤率 (5xx)", "stat",
    ['sum(rate(http_requests_total{path="/chat",status=~"5.."}[5m])) / sum(rate(http_requests_total{path="/chat"}[5m]))'],
    6, 0, 6, 4, unit="percentunit", decimals=1,
    desc="5xx 佔 /chat 請求的比例。502 = Gemini 呼叫失敗(逾時、額度用完等)。",
    thresholds=[(None, "green"), (0.01, "red")]))
panels.append(panel(
    "近 1 小時 token 用量", "stat",
    ['sum by (type) (increase(llm_tokens_total{type!="cache_read"}[1h]))'], 12, 0, 6, 4, unit="short",
    legend=["{{type}}"], decimals=0,
    desc="input / output token 累計。cache_read 是 input 的子集(Gemini implicit caching 命中量),另列在下方。"))
panels.append(panel(
    "估算成本 (USD / 小時)", "stat",
    ['(sum(increase(llm_tokens_total{type="input"}[1h])) * $price_in + sum(increase(llm_tokens_total{type="output"}[1h])) * $price_out) / 1000000'],
    18, 0, 6, 4, unit="currencyUSD", decimals=4,
    desc="token 用量 × 單價的『估算值』,不是實際帳單。單價在頁面上方的變數可調。input 以全價計,所以是偏高的上限(未扣 cache 折扣)。"))

# 第二列:流量與延遲
panels.append(panel(
    "請求率(依 path / status)", "timeseries",
    ['sum by (path, status) (rate(http_requests_total[1m]))'], 0, 4, 12, 8, unit="reqps",
    legend=["{{path}} {{status}}"]))
panels.append(panel(
    "/chat 延遲 p50 / p95", "timeseries",
    ['histogram_quantile(0.50, sum by (le) (rate(http_request_duration_seconds_bucket{path="/chat"}[5m])))',
     'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{path="/chat"}[5m])))'],
    12, 4, 12, 8, unit="s", legend=["p50", "p95"],
    desc="整個 /chat 的延遲(含 Mongo 寫入)。Day 13 的 SLO:95% 請求 < 3s。"))

# 第三列:LLM 本身
panels.append(panel(
    "LLM 呼叫延遲 p50 / p95", "timeseries",
    ['histogram_quantile(0.50, sum by (le) (rate(llm_request_duration_seconds_bucket[5m])))',
     'histogram_quantile(0.95, sum by (le) (rate(llm_request_duration_seconds_bucket[5m])))'],
    0, 12, 12, 8, unit="s", legend=["p50", "p95"],
    desc="只算呼叫 Gemini 那一段。跟上面 /chat 延遲相比,差距就是我們自己程式(含 Mongo)花的時間。"))
panels.append(panel(
    "LLM 呼叫結果", "timeseries",
    ['sum by (status) (increase(llm_requests_total[5m]))'], 12, 12, 12, 8, unit="short",
    legend=["{{status}}"], desc="ok / error。error 暴增通常是 429 額度用完或逾時。"))

# 第四列:token 與每個 pod
panels.append(panel(
    "token 用量(每 5 分鐘)", "timeseries",
    ['sum by (type) (increase(llm_tokens_total[5m]))'], 0, 20, 12, 8, unit="short", legend=["{{type}}"],
    desc="cache_read = Gemini implicit caching 命中量。短對話通常是 0(門檻 2.5 系列 2,048 / 3.x 系列 4,096 token),這裡只觀測、不優化。"))
panels.append(panel(
    "各 Pod 的 /chat 請求率", "timeseries",
    ['sum by (pod) (rate(http_requests_total{path="/chat"}[1m]))'], 12, 20, 12, 8, unit="reqps", legend=["{{pod}}"],
    desc="HPA 擴到多個 replica 後,流量是否均分。"))

# ---- Day 13:SLO 區塊(放最上面,先看「有沒有守住承諾」)-----------------------
SLO_H = 12
for p_ in panels:
    p_["gridPos"]["y"] += SLO_H
slo = []
slo.append(panel(
    "可用性 SLI (近 1h)", "stat",
    ['1 - sli:chat_error_ratio:rate1h'], 0, 0, 5, 4, unit="percentunit", decimals=2,
    desc="SLO:99%。= 1 - (/chat 5xx 比例)。無流量時顯示 N/A。",
    thresholds=[(None, "red"), (0.99, "green")]))
slo.append(panel(
    "可用性 burn rate (1h)", "stat",
    ['sli:chat_error_ratio:rate1h / 0.01'], 5, 0, 5, 4, unit="short", decimals=1,
    desc="預算消耗速度。1 = 剛好花完;>14.4 且 5m 窗也超標 → ChatAvailabilityFastBurn 告警。",
    thresholds=[(None, "green"), (1, "yellow"), (14.4, "red")]))
slo.append(panel(
    "延遲 SLI:<12s 比例 (近 1h)", "stat",
    ['1 - sli:chat_slow_ratio:rate1h'], 10, 0, 5, 4, unit="percentunit", decimals=2,
    desc="SLO:95% 的 /chat 在 12 秒內。12 秒來自 Day 12 實測 p95 ≈ 9.75s(Gemini reasoning),不是照搬 3s。",
    thresholds=[(None, "red"), (0.95, "green")]))
slo.append(panel(
    "延遲 burn rate (1h)", "stat",
    ['sli:chat_slow_ratio:rate1h / 0.05'], 15, 0, 5, 4, unit="short", decimals=1,
    thresholds=[(None, "green"), (1, "yellow"), (14.4, "red")]))
slo.append(panel(
    "Firing 中的告警", "stat",
    ['count(ALERTS{alertstate="firing",alertname=~"Chat.*|LLM.*"}) or vector(0)'], 20, 0, 4, 4, unit="short", decimals=0,
    thresholds=[(None, "green"), (1, "red")]))
slo.append(panel(
    "Burn rate 時間序列(1h 窗)", "timeseries",
    ['sli:chat_error_ratio:rate1h / 0.01', 'sli:chat_slow_ratio:rate1h / 0.05', 'vector(14.4)'],
    0, 4, 12, 8, unit="short", legend=["可用性", "延遲", "快燒門檻 14.4"],
    desc="線超過 14.4 的虛線,且 5 分鐘窗也超標 2 分鐘 → 告警。"))
slo.append(panel(
    "Token / 小時 vs 基準", "timeseries",
    ['llm:tokens_per_hour:increase1h',
     'clamp_min(llm:tokens_per_hour:baseline23h * 3, 20000)'],
    12, 4, 12, 8, unit="short", legend=["近 1h 用量", "告警門檻 max(3×基準, 下限)"],
    desc="成本護欄:用量線超過門檻線 5 分鐘 → LLMTokenUsageSpike。基準 = 前 23 小時平均(排除最近 1 小時)。"))
panels = slo + panels

dash = {
    "uid": "chatbot-overview",
    "title": "Chatbot Overview",
    "tags": ["chatbot"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "30s",
    "time": {"from": "now-1h", "to": "now"},
    "templating": {"list": [
        {"name": "price_in", "label": "input 單價 (USD / 1M tokens)", "type": "textbox",
         "query": "0.30", "current": {"text": "0.30", "value": "0.30"}},
        {"name": "price_out", "label": "output 單價 (USD / 1M tokens)", "type": "textbox",
         "query": "2.50", "current": {"text": "2.50", "value": "2.50"}},
    ]},
    "panels": panels,
}

from pathlib import Path
out = str(Path(__file__).resolve().parent.parent / "mychart/dashboards/chatbot-overview.json")
import os
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(dash, open(out, "w", encoding="utf8"), ensure_ascii=False, indent=2)
print("wrote", out, len(panels), "panels")
