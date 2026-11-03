"""Redis cache-aside 邏輯的測試:用 fakeredis 和一個極簡的假 Mongo collection。"""
import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from chat_store import KEY_PREFIX, ChatHistoryStore
from conftest import FakeCol
from metrics import CACHE_REQUESTS


@pytest.fixture
def parts():
    r = fakeredis.FakeRedis(decode_responses=True)
    col = FakeCol()
    return ChatHistoryStore(col=col, redis_client=r, ttl_seconds=60, max_messages=4), col, r


def count(result):
    return CACHE_REQUESTS.labels(result)._value.get()


def test_first_read_misses_then_hits(parts):
    store, col, r = parts
    m0, h0 = count("miss"), count("hit")
    store.append_turn("c", "u", "q1", "a1")  # 寫入時 key 不存在 → 不寫快取
    assert r.exists(KEY_PREFIX + "c") == 0
    assert len(store.get_history("c")) == 2  # miss,從 Mongo 回填
    assert count("miss") == m0 + 1
    assert len(store.get_history("c")) == 2  # hit
    assert count("hit") == h0 + 1


def test_write_through_keeps_cache_and_mongo_identical(parts):
    store, col, r = parts
    store.append_turn("c", "u", "q1", "a1")
    store.get_history("c")  # 回填
    store.append_turn("c", "u", "q2", "a2")  # key 在 → 直接追加
    cached = [__import__("json").loads(x) for x in r.lrange(KEY_PREFIX + "c", 0, -1)]
    assert cached == store._mongo_history("c")
    assert [m["content"] for m in cached] == ["q1", "a1", "q2", "a2"]


def test_cache_is_trimmed_to_max_messages(parts):
    store, col, r = parts
    store.append_turn("c", "u", "q1", "a1")
    store.get_history("c")
    for i in range(2, 5):
        store.append_turn("c", "u", f"q{i}", f"a{i}")
    assert r.llen(KEY_PREFIX + "c") == 4  # max_messages=4


def test_cache_hit_and_miss_give_llm_identical_context(parts):
    store, col, r = parts
    for i in range(1, 5):
        store.append_turn("c", "u", f"q{i}", f"a{i}")
    cold = store.get_history("c")  # miss → Mongo
    warm = store.get_history("c")  # hit → Redis
    assert cold == warm and len(cold) == 4


def test_ttl_expiry_rebuilds_from_mongo(parts):
    store, col, r = parts
    store.append_turn("c", "u", "q1", "a1")
    store.get_history("c")
    assert 0 < r.ttl(KEY_PREFIX + "c") <= 60
    r.delete(KEY_PREFIX + "c")  # 模擬 TTL 到期
    assert len(store.get_history("c")) == 2


def test_mongo_failure_leaves_cache_untouched(parts):
    store, col, r = parts
    store.append_turn("c", "u", "q1", "a1")
    store.get_history("c")
    col.fail = True
    with pytest.raises(RuntimeError):
        store.append_turn("c", "u", "q2", "a2")
    assert r.llen(KEY_PREFIX + "c") == 2  # 沒寫成 Mongo,快取也不能多出內容


def test_redis_down_degrades_to_mongo(parts):
    store, col, r = parts
    store.append_turn("c", "u", "q1", "a1")

    class DeadRedis:
        def __getattr__(self, name):
            def boom(*a, **k):
                raise RedisConnectionError("down")

            return boom

    store._redis = DeadRedis()
    e0 = count("error")
    assert len(store.get_history("c")) == 2  # 變慢但不壞
    assert count("error") == e0 + 1
    store.append_turn("c", "u", "q2", "a2")  # 寫入也不會因 Redis 掛掉而失敗
    assert len(store._mongo_history("c")) == 4
