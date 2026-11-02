"""測試共用設定。

重點:測試絕不能打真的 Gemini 或 Mongo(慢、花錢、CI 上也沒有金鑰)。
所以每個測試都把 main.llm 換成替身、main.store 換成「沒啟用」的版本。
"""
import os

# main.py 一 import 就會讀環境變數並建立 store;先清掉,避免本機 .env 的真金鑰混進測試。
for key in ("GOOGLE_API_KEY", "FAKE_LLM", "MONGO_HOST", "MONGO_USERNAME", "MONGO_PASSWORD"):
    os.environ.pop(key, None)

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

import main
from chat_store import ChatHistoryStore


class StubLLM:
    """記下收到的訊息,回固定答案。"""

    def __init__(self, reply="stub reply"):
        self.reply = reply
        self.calls = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        return AIMessage(
            content=self.reply,
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "input_token_details": {"cache_read": 0},
            },
        )


class BrokenLLM:
    def invoke(self, messages):
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(main, "llm", None)
    monkeypatch.setattr(main, "store", ChatHistoryStore())  # 無 Mongo/Redis → 程序內 dict
    yield


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def stub_llm(monkeypatch):
    llm = StubLLM()
    monkeypatch.setattr(main, "llm", llm)
    return llm
