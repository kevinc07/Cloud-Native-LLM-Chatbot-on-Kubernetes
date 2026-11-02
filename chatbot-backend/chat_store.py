"""對話紀錄的儲存層:MongoDB = source of truth,Redis = 快取(cache-aside)。

main.py 只呼叫這裡的 get_history / append_turn,不直接碰 pymongo 或 redis。

讀取(get_history):
    1. 先查 Redis(key = chat:<conversation_id>,值是最近 N 則訊息)。命中就直接回。
    2. 沒命中(miss:過期、冷啟動、新對話)→ 從 Mongo 讀最近 N 則 → 回填 Redis 並設 TTL。
    3. Redis 連不上 → 降級為直讀 Mongo(變慢但不壞),不回填,記一筆 error。
寫入(append_turn):
    1. 先寫 Mongo(唯一的 source of truth)。失敗就丟例外,呼叫端回 503,快取完全不動。
    2. Mongo 成功後更新 Redis:key 還在就 append + 截斷 + 重設 TTL;key 不在就不寫(下次讀取從 Mongo 重建)。
       寫 Redis 失敗就嘗試 DEL 該 key,只記 log、不中斷服務;TTL 是最後一道保險。

不變的規則:無論命中與否,送給 LLM 的永遠是「最近 N 則」——快取只影響延遲,不影響模型看到的內容。
已知限制:同一段對話的併發請求沒有加鎖,極端情況下 Redis 與 Mongo 的順序可能暫時不一致(TTL 到期後自癒)。
"""
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote_plus

from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from metrics import CACHE_REQUESTS

__all__ = ["ChatHistoryStore", "PyMongoError"]

KEY_PREFIX = "chat:"


class ChatHistoryStore:
    def __init__(self, col=None, redis_client=None, ttl_seconds=1800, max_messages=20):
        # col=None(沒設 Mongo,例如本機直接跑)→ 退回程序內的 dict,只供開發用。
        self._col = col
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._max = max_messages
        self._index_ready = False
        self._local: dict[str, list[dict]] = {}

    @property
    def enabled(self) -> bool:
        return self._col is not None

    @property
    def cache_enabled(self) -> bool:
        return self._redis is not None

    @classmethod
    def from_env(cls) -> "ChatHistoryStore":
        """帳密由 K8s Secret 注入(MONGO_USERNAME / MONGO_PASSWORD),不寫死。"""
        host = os.getenv("MONGO_HOST", "")
        port = os.getenv("MONGO_PORT", "27017")
        username = os.getenv("MONGO_USERNAME", "")
        password = os.getenv("MONGO_PASSWORD", "")
        db = os.getenv("MONGO_DB", "chatbot")

        col = None
        if host and username and password:
            # 帳密要 URL-encode,密碼含 @ : / 之類字元時才不會把 URI 弄壞。
            client = MongoClient(
                f"mongodb://{quote_plus(username)}:{quote_plus(password)}"
                f"@{host}:{port}/?authSource=admin",
                serverSelectionTimeoutMS=3000,
            )
            col = client[db]["conversations"]

        redis_client = None
        redis_host = os.getenv("REDIS_HOST", "")
        if redis_host:
            import redis

            # 短逾時:Redis 掛掉時要快速失敗並降級,不能把每個請求都拖住。
            redis_client = redis.Redis(
                host=redis_host,
                port=int(os.getenv("REDIS_PORT", "6379")),
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                decode_responses=True,
            )
        return cls(
            col=col,
            redis_client=redis_client,
            ttl_seconds=int(os.getenv("REDIS_TTL_SECONDS", "1800")),
            max_messages=int(os.getenv("HISTORY_MAX_MESSAGES", "20")),
        )

    # ---- Mongo ------------------------------------------------------------
    def ensure_index(self) -> None:
        """替 conversation_id 建唯一索引(冪等)。啟動時 Mongo 可能還沒 ready,
        所以失敗只記 log,第一次寫入前會再試一次。"""
        if not self.enabled or self._index_ready:
            return
        try:
            self._col.create_index([("conversation_id", ASCENDING)], unique=True)
            self._index_ready = True
        except PyMongoError as e:
            print(f"[mongo] create_index failed, will retry: {e}", flush=True)

    def _mongo_history(self, conversation_id: str) -> list[dict]:
        doc = self._col.find_one(
            {"conversation_id": conversation_id},
            {"_id": 0, "messages": {"$slice": -self._max}},
        )
        if not doc:
            return []
        return [{"role": m["role"], "content": m["content"]} for m in doc["messages"]]

    # ---- 讀 ---------------------------------------------------------------
    def get_history(self, conversation_id: str) -> list[dict]:
        """回傳最近 N 則 [{"role","content"}, ...]。Mongo 讀取失敗會丟 PyMongoError。"""
        if not self.enabled:
            return list(self._local.get(conversation_id, []))[-self._max :]

        key = KEY_PREFIX + conversation_id
        cache_ok = self._redis is not None
        if cache_ok:
            try:
                raw = self._redis.lrange(key, 0, -1)
                if raw:
                    CACHE_REQUESTS.labels("hit").inc()
                    return [json.loads(x) for x in raw]
                CACHE_REQUESTS.labels("miss").inc()
            except RedisError as e:
                cache_ok = False
                CACHE_REQUESTS.labels("error").inc()
                print(f"[redis] read failed, falling back to mongo: {e}", flush=True)

        history = self._mongo_history(conversation_id)
        if cache_ok and history:
            self._refill(key, history)
        return history

    def _refill(self, key: str, history: list[dict]) -> None:
        try:
            pipe = self._redis.pipeline()  # 預設 transaction=True(MULTI/EXEC)
            pipe.delete(key)
            pipe.rpush(key, *[json.dumps(m, ensure_ascii=False) for m in history])
            pipe.expire(key, self._ttl)
            pipe.execute()
        except RedisError as e:
            print(f"[redis] refill failed (ignored): {e}", flush=True)

    # ---- 寫 ---------------------------------------------------------------
    def append_turn(
        self, conversation_id: str, user_id: str, user_text: str, bot_text: str
    ) -> None:
        """把一輪對話(user + bot 兩則)寫進 Mongo,成功後更新快取。
        Mongo 寫入失敗會丟 PyMongoError,由呼叫端決定怎麼處理。"""
        if not self.enabled:
            hist = self._local.setdefault(conversation_id, [])
            hist += [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": bot_text},
            ]
            del hist[: -self._max]
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
        if self._redis is not None:
            self._update_cache(conversation_id, user_text, bot_text)

    def _update_cache(self, conversation_id: str, user_text: str, bot_text: str) -> None:
        key = KEY_PREFIX + conversation_id
        new = [
            json.dumps({"role": "user", "content": user_text}, ensure_ascii=False),
            json.dumps({"role": "assistant", "content": bot_text}, ensure_ascii=False),
        ]

        def txn(pipe):
            # WATCH 著 key:EXISTS 之後到 EXEC 之前若有人動過它,交易會失敗並重試。
            # key 不在就不寫——只寫進 2 則會讓快取裡出現「殘缺的歷史」,下次讀取從 Mongo 重建才正確。
            if pipe.exists(key):
                pipe.multi()
                pipe.rpush(key, *new)
                pipe.ltrim(key, -self._max, -1)
                pipe.expire(key, self._ttl)

        try:
            self._redis.transaction(txn, key)
        except RedisError as e:
            print(f"[redis] write failed, invalidating key: {e}", flush=True)
            try:
                self._redis.delete(key)
            except RedisError:
                pass  # 連 DEL 都失敗:交給 TTL 兜底
