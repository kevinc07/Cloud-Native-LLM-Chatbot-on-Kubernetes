"""Prometheus 指標定義。

Prometheus 是 pull 模型:它定期來打 GET /metrics,把這裡累積的數字抓走。
所以程式只要「記數」,不用主動推送。

指標型別:
- Counter:只增不減的累計值(請求數、token 數)。用 rate()/increase() 看變化。
- Histogram:把數值分到桶(bucket)裡,可以算 p95 等百分位數(延遲用)。

label 的基數要小:label 值的每一種組合都是一條獨立的時間序列。
所以 path 用「路由樣板」(/chat),不是實際 URL;絕不放 user_id、conversation_id。
"""
import time

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# --- HTTP 層(infra 觀測):每個端點的請求數與延遲 ---------------------------
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests handled",
    ["method", "path", "status"],
)
# bucket 邊界一定要剛好落在 SLO 門檻上:/health 要 <200ms(0.2)、/chat 要 <12s(12)。
# PromQL 算「小於門檻的比例」是直接取門檻那個 bucket,門檻不在邊界上就只能估算。
# (SLO 實測依據:Day 12 量到 /chat p95 約 9.75s,主因是 Gemini 的 reasoning。)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 3, 5, 8, 12, 20, 30, 60),
)

# --- LLM 層(AI 觀測):呼叫 Gemini 的延遲、結果、token 用量 -------------------
LLM_REQUESTS = Counter(
    "llm_requests_total",
    "LLM calls by outcome",
    ["model", "status"],  # status: ok | error
)
LLM_LATENCY = Histogram(
    "llm_request_duration_seconds",
    "LLM call latency",
    ["model"],
    buckets=(0.5, 1, 2, 3, 5, 8, 12, 20, 30, 60),
)
# type: input | output | cache_read。Day 12 用它估成本,Day 13 用它做成本護欄告警。
# cache_read 是 input 的子集(Gemini implicit caching 命中量),只觀測、不優化。
LLM_TOKENS = Counter(
    "llm_tokens_total",
    "LLM tokens used",
    ["model", "type"],
)

# --- 快取層:Redis cache-aside 的命中情況(Day 20)------------------------------
# result: hit(Redis 有)| miss(Redis 沒有,改讀 Mongo 並回填)| error(Redis 連不上,降級直讀 Mongo)
CACHE_REQUESTS = Counter(
    "cache_requests_total",
    "Conversation history lookups by cache result",
    ["result"],
)


def init_series(model: str) -> None:
    """啟動時把已知的時間序列先建立成 0。

    Counter / Histogram 的 labels(...) 第一次被呼叫才會產生那條序列,所以第一次請求之後
    Prometheus 抓到的第一筆就已經 > 0,沒有「前一筆」可比,rate()/increase() 會漏掉那次增量;
    而且「從來沒出現過」的序列(例如 5xx)會讓 SLI 的分子變成『沒有資料』而不是 0。
    預先建立可以兩個問題一起避免。
    """
    for method, path, statuses in (
        ("POST", "/chat", ("200", "422", "500", "502", "503")),
        ("GET", "/health", ("200",)),
    ):
        for status in statuses:
            HTTP_REQUESTS.labels(method, path, status)
        HTTP_LATENCY.labels(method, path)
    for status in ("ok", "error"):
        LLM_REQUESTS.labels(model, status)
    LLM_LATENCY.labels(model)
    for result in ("hit", "miss", "error"):
        CACHE_REQUESTS.labels(result)
    for token_type in ("input", "output", "cache_read"):
        LLM_TOKENS.labels(model, token_type)


def record_llm_usage(model: str, usage: dict | None) -> None:
    """從 LangChain 回傳的 usage_metadata 記 token 用量。"""
    if not usage:
        return
    LLM_TOKENS.labels(model, "input").inc(usage.get("input_tokens", 0))
    LLM_TOKENS.labels(model, "output").inc(usage.get("output_tokens", 0))
    cache_read = (usage.get("input_token_details") or {}).get("cache_read", 0)
    LLM_TOKENS.labels(model, "cache_read").inc(cache_read or 0)


async def metrics_middleware(request: Request, call_next):
    if request.url.path == "/metrics":  # 不統計抓指標本身
        return await call_next(request)

    start = time.perf_counter()
    status = "500"
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    finally:
        # 路由比對完成後,scope 裡才有 route。比對不到(404 掃描、亂打)統一記成
        # "unmatched",避免有人亂打網址就製造無限多條時間序列。
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        HTTP_REQUESTS.labels(request.method, path, status).inc()
        HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - start)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
