"""對話紀錄的儲存層(MongoDB = source of truth)。

main.py 只呼叫這裡的 ChatHistoryStore 介面(append_turn / get_history),
不直接碰 pymongo。這樣 Day 20 要在前面加 Redis 快取時,只需要改這個檔案,
main.py 不用動。
"""
import os
from datetime import datetime, timezone
from urllib.parse import quote_plus

from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError

__all__ = ["ChatHistoryStore", "PyMongoError"]


class ChatHistoryStore:
    """帳密由 K8s Secret 注入(MONGO_USERNAME / MONGO_PASSWORD),不寫死。
    沒設連線資訊(例如本機直接跑)時 enabled=False,所有方法都安靜地什麼都不做。"""

    def __init__(self) -> None:
        host = os.getenv("MONGO_HOST", "")
        port = os.getenv("MONGO_PORT", "27017")
        username = os.getenv("MONGO_USERNAME", "")
        password = os.getenv("MONGO_PASSWORD", "")
        db = os.getenv("MONGO_DB", "chatbot")

        self.enabled = bool(host and username and password)
        self._index_ready = False
        self._col = None
        if self.enabled:
            # 帳密要 URL-encode,密碼含 @ : / 之類字元時才不會把 URI 弄壞。
            client = MongoClient(
                f"mongodb://{quote_plus(username)}:{quote_plus(password)}"
                f"@{host}:{port}/?authSource=admin",
                serverSelectionTimeoutMS=3000,
            )
            self._col = client[db]["conversations"]

    def ensure_index(self) -> None:
        """替 conversation_id 建唯一索引(冪等,已存在就什麼都不做)。
        啟動時 Mongo 可能還沒 ready,所以失敗只記 log,第一次寫入前會再試一次。"""
        if not self.enabled or self._index_ready:
            return
        try:
            self._col.create_index([("conversation_id", ASCENDING)], unique=True)
            self._index_ready = True
        except PyMongoError as e:
            print(f"[mongo] create_index failed, will retry: {e}", flush=True)

    def append_turn(
        self, conversation_id: str, user_id: str, user_text: str, bot_text: str
    ) -> None:
        """把一輪對話(user + bot 兩則)寫進 Mongo。upsert:第一輪建文件,之後 push。
        summary / summarized_up_to 先保留欄位、不實作(Day 21 選做)。
        寫入失敗會丟 PyMongoError,由呼叫端決定怎麼處理。"""
        if not self.enabled:
            return
        self.ensure_index()
        now = datetime.now(timezone.utc)
        self._col.update_one(
            {"conversation_id": conversation_id},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "summary": None,
                    "summarized_up_to": 0,
                },
                "$push": {
                    "messages": {
                        "$each": [
                            {"role": "user", "content": user_text, "ts": now},
                            {"role": "assistant", "content": bot_text, "ts": now},
                        ]
                    }
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )

    def get_history(self, conversation_id: str, limit: int = 20) -> list[dict]:
        """讀取某段對話最近 limit 則訊息,格式 [{"role", "content"}, ...]。
        目前 main.py 還沒用它(Day 9 故意讓記憶留在 pod 的記憶體裡暴露 bug),
        Day 20 才會改成靠它修好。找不到或沒啟用就回空 list。"""
        if not self.enabled:
            return []
        doc = self._col.find_one(
            {"conversation_id": conversation_id},
            {"_id": 0, "messages": {"$slice": -limit}},
        )
        if not doc:
            return []
        return [{"role": m["role"], "content": m["content"]} for m in doc["messages"]]
