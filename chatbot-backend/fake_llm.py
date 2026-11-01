"""假的 LLM(測試替身),用來做負載測試與故障注入,不消耗 Gemini 額度。

FAKE_LLM=true 時,main.py 用它取代真的 ChatGoogleGenerativeAI。它跟真的一樣有
.invoke(messages),回傳帶 usage_metadata 的 AIMessage,所以 metrics 與下游程式完全不用改。

可注入的故障(環境變數,預設都是「正常」):
- FAKE_LLM_DELAY_SECONDS:每次呼叫先 sleep 這麼久(模擬 Gemini 變慢)→ Day 13 延遲告警
- FAKE_LLM_ERROR_RATE:0~1,以此機率丟例外(模擬 429 / 逾時)→ Day 13 成功率告警、Day 27 演練
- FAKE_LLM_OUTPUT_TOKENS:回報的 output token 數(模擬 token 暴增)→ Day 13 成本護欄告警

這是演練工具,正式環境不應開啟(values.yaml 預設 fakeLlm.enabled=false)。
"""
import os
import random
import time

from langchain_core.messages import AIMessage


class FakeLLM:
    def __init__(self, delay: float, error_rate: float, input_tokens: int, output_tokens: int):
        self.delay = delay
        self.error_rate = error_rate
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    @classmethod
    def from_env(cls) -> "FakeLLM":
        return cls(
            delay=float(os.getenv("FAKE_LLM_DELAY_SECONDS", "0")),
            error_rate=float(os.getenv("FAKE_LLM_ERROR_RATE", "0")),
            input_tokens=int(os.getenv("FAKE_LLM_INPUT_TOKENS", "100")),
            output_tokens=int(os.getenv("FAKE_LLM_OUTPUT_TOKENS", "300")),
        )

    def invoke(self, messages):
        if self.delay > 0:
            time.sleep(self.delay)
        if random.random() < self.error_rate:
            raise RuntimeError("injected fault: simulated LLM failure")
        return AIMessage(
            content="[fake llm] ok",
            usage_metadata={
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
                "input_token_details": {"cache_read": 0},
            },
        )
