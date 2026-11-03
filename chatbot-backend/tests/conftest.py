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
from pymongo.errors import DuplicateKeyError


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


class FakeCol:
    """store 用到的 Mongo collection 子集:upsert(含 conversation_id 唯一索引)、find_one、find().sort().limit()、delete_one。"""

    def __init__(self):
        self.docs = {}
        self.fail = False

    def create_index(self, *a, **k):
        pass

    def update_one(self, flt, update, upsert=False):
        if self.fail:
            raise RuntimeError("mongo down")
        cid = flt["conversation_id"]
        doc = self.docs.get(cid)
        if doc is not None and "user_id" in flt and doc.get("user_id") != flt["user_id"]:
            raise DuplicateKeyError("E11000 duplicate key")  # 真的 Mongo 在 upsert 變插入時的行為
        if doc is None:
            doc = {"conversation_id": cid, "messages": []}
            if "user_id" in flt:
                doc["user_id"] = flt["user_id"]
            doc.update(update.get("$setOnInsert", {}))
            self.docs[cid] = doc
        doc["messages"] += update["$push"]["messages"]["$each"]
        doc.update(update.get("$set", {}))

    @staticmethod
    def _match(doc, flt):
        return all(doc.get(k) == v for k, v in flt.items())

    @staticmethod
    def _project(doc, proj):
        out = dict(doc)
        n = (proj or {}).get("messages", {})
        if isinstance(n, dict) and "$slice" in n:
            k = n["$slice"]
            out["messages"] = doc["messages"][k:] if k < 0 else doc["messages"][:k]
        return out

    def find_one(self, flt, proj=None):
        for doc in self.docs.values():
            if self._match(doc, flt):
                return self._project(doc, proj)
        return None

    def find(self, flt, proj=None):
        rows = [self._project(d, proj) for d in self.docs.values() if self._match(d, flt)]

        class Cursor(list):
            def sort(self, key, direction):
                super().sort(key=lambda d: d.get(key), reverse=direction < 0)
                return self

            def limit(self, n):
                return Cursor(self[:n])

        return Cursor(rows)

    def delete_one(self, flt):
        for cid, doc in list(self.docs.items()):
            if self._match(doc, flt):
                del self.docs[cid]
                return type("R", (), {"deleted_count": 1})()
        return type("R", (), {"deleted_count": 0})()


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
