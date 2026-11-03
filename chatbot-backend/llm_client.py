"""呼叫 LLM 的重試策略:次數有上限、退避有間隔、整體有期限。

為什麼自己管重試:langchain-google-genai 預設 max_retries=6、timeout=None(Day 27 實查)。
外部服務變慢或回錯時,每個 /chat 會在 SDK 裡悄悄打最多 7 次、而且可能永遠不逾時——
重試本來是為了擋瞬間抖動,卻變成「對一個已經不健康的依賴放大 7 倍流量」(retry storm),
同時把 worker 執行緒卡住、延遲與成本一起爆。

所以:SDK 的重試關掉(max_retries=0)、單次呼叫設逾時,重試改由這裡統一處理,
每一次嘗試都記進 llm_attempts_total,放大倍數(嘗試數 ÷ 請求數)可以被觀測與告警。

規則:
- 最多 max_attempts 次(含第一次)。
- 第 n 次失敗後等 min(cap, base * 2^(n-1)) 秒,再乘 0.5~1.0 的隨機係數(jitter),
  避免多個 replica 同時重試、同時打回去。
- 預估「等待後」會超過 deadline 就不再試,直接失敗。
- 429(額度/限流)不重試:額度用完時重試只會更快撞牆。
"""
import os
import random
import time
from dataclasses import dataclass

from metrics import LLM_ATTEMPTS


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    backoff_base: float = 0.5
    backoff_cap: float = 4.0
    deadline: float = 30.0  # 整個 LLM 呼叫(含重試與等待)最多花幾秒

    @classmethod
    def from_env(cls) -> "RetryPolicy":
        return cls(
            max_attempts=int(os.getenv("LLM_MAX_ATTEMPTS", "2")),
            backoff_base=float(os.getenv("LLM_BACKOFF_BASE_SECONDS", "0.5")),
            backoff_cap=float(os.getenv("LLM_BACKOFF_CAP_SECONDS", "4")),
            deadline=float(os.getenv("LLM_DEADLINE_SECONDS", "30")),
        )


def is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".upper()
    return not ("429" in text or "RESOURCE_EXHAUSTED" in text or "QUOTA" in text)


def invoke_with_retry(llm, messages, policy: RetryPolicy, model: str,
                      sleep=time.sleep, clock=time.monotonic, rand=random.random):
    start = clock()
    attempt = 0
    while True:
        attempt += 1
        try:
            result = llm.invoke(messages)
        except Exception as exc:
            LLM_ATTEMPTS.labels(model, "error").inc()
            if attempt >= policy.max_attempts or not is_retryable(exc):
                raise
            wait = min(policy.backoff_cap, policy.backoff_base * 2 ** (attempt - 1)) * (0.5 + rand() / 2)
            if clock() - start + wait > policy.deadline:
                raise
            print(f"[llm] attempt {attempt} failed ({type(exc).__name__}); retry in {wait:.2f}s", flush=True)
            sleep(wait)
            continue
        LLM_ATTEMPTS.labels(model, "ok").inc()
        return result
