"""一個使用者多段對話 + 擁有者檢查。用真的 ChatHistoryStore 搭配假 Mongo。

重點是安全性質:別人的對話,讀、寫、刪都必須是 404,而且不能洩漏「這個 id 存在」。
"""
import fakeredis
import pytest

import main
from chat_store import ChatHistoryStore
from conftest import FakeCol


@pytest.fixture
def mongo_store(monkeypatch):
    col = FakeCol()
    store = ChatHistoryStore(col=col, redis_client=fakeredis.FakeRedis(decode_responses=True), ttl_seconds=60, max_messages=20)
    monkeypatch.setattr(main, "store", store)
    return store, col


def alice(extra=None):
    return {"X-User-Id": "alice", **(extra or {})}


def bob():
    return {"X-User-Id": "bob"}


def say(client, headers, text, cid=None):
    body = {"message": text}
    if cid:
        body["conversation_id"] = cid
    return client.post("/chat", json=body, headers=headers)


def test_missing_user_header_is_401(client, mongo_store):
    assert client.get("/conversations").status_code == 401
    assert client.get("/conversations/x").status_code == 401
    assert client.delete("/conversations/x").status_code == 401
    assert client.post("/chat", json={"message": "hi"}).status_code == 401


def test_invalid_user_id_is_422(client, mongo_store):
    assert client.get("/conversations", headers={"X-User-Id": "a b/c"}).status_code == 422
    assert client.get("/conversations", headers={"X-User-Id": "x" * 65}).status_code == 422


def test_legacy_body_user_id_still_works_without_header(client, mongo_store):
    r = client.post("/chat", json={"user_id": "legacy", "message": "hi"})
    assert r.status_code == 200 and r.json()["user_id"] == "legacy"


def test_one_user_can_have_many_conversations_newest_first(client, mongo_store):
    c1 = say(client, alice(), "first topic").json()["conversation_id"]
    c2 = say(client, alice(), "second topic").json()["conversation_id"]
    say(client, alice(), "more on first", cid=c1)  # c1 更新 → 排到最前
    rows = client.get("/conversations", headers=alice()).json()["conversations"]
    assert [r["id"] for r in rows] == [c1, c2]
    assert rows[0]["title"] == "first topic"  # 標題取第一則訊息,不隨後續訊息改變


def test_long_title_is_truncated(client, mongo_store):
    say(client, alice(), "x" * 100)
    title = client.get("/conversations", headers=alice()).json()["conversations"][0]["title"]
    assert len(title) == 31 and title.endswith("…")


def test_list_only_shows_own_conversations(client, mongo_store):
    say(client, alice(), "alice secret")
    assert client.get("/conversations", headers=bob()).json()["conversations"] == []


def test_get_conversation_returns_full_messages(client, mongo_store):
    cid = say(client, alice(), "hello").json()["conversation_id"]
    say(client, alice(), "again", cid=cid)
    body = client.get(f"/conversations/{cid}", headers=alice()).json()
    assert [m["content"] for m in body["messages"]][::2] == ["hello", "again"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user", "assistant"]


def test_full_history_is_not_capped_by_llm_window(client, mongo_store, monkeypatch):
    store, _ = mongo_store
    monkeypatch.setattr(store, "_max", 4)
    cid = say(client, alice(), "t0").json()["conversation_id"]
    for i in range(1, 5):
        say(client, alice(), f"t{i}", cid=cid)
    assert len(client.get(f"/conversations/{cid}", headers=alice()).json()["messages"]) == 10


def test_other_users_conversation_is_404_for_read(client, mongo_store):
    cid = say(client, alice(), "private").json()["conversation_id"]
    assert client.get(f"/conversations/{cid}", headers=bob()).status_code == 404


def test_other_users_conversation_is_404_for_chat_and_is_not_modified(client, mongo_store):
    store, col = mongo_store
    cid = say(client, alice(), "private").json()["conversation_id"]
    before = len(col.docs[cid]["messages"])
    assert say(client, bob(), "intruding", cid=cid).status_code == 404
    assert len(col.docs[cid]["messages"]) == before


def test_other_users_conversation_is_404_for_delete_and_survives(client, mongo_store):
    cid = say(client, alice(), "private").json()["conversation_id"]
    assert client.delete(f"/conversations/{cid}", headers=bob()).status_code == 404
    assert client.get(f"/conversations/{cid}", headers=alice()).status_code == 200


def test_unknown_and_foreign_ids_look_identical(client, mongo_store):
    cid = say(client, alice(), "private").json()["conversation_id"]
    foreign = client.get(f"/conversations/{cid}", headers=bob())
    unknown = client.get("/conversations/does-not-exist", headers=bob())
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()


def test_cache_does_not_bypass_ownership(client, mongo_store):
    """alice 的歷史在 Redis 裡是熱的,bob 仍然讀不到。"""
    store, _ = mongo_store
    cid = say(client, alice(), "warm").json()["conversation_id"]
    store.get_history(cid)  # 確保快取已熱
    assert store._redis.exists("chat:" + cid)
    assert say(client, bob(), "peek", cid=cid).status_code == 404


def test_race_for_same_new_id_loser_gets_404(client, mongo_store, monkeypatch):
    """兩人同時搶同一個新 id:get_owner 都看到「不存在」,輸的在 upsert 被唯一索引擋下。"""
    store, col = mongo_store
    assert say(client, alice(), "I was first", cid="shared-id").status_code == 200
    monkeypatch.setattr(store, "get_owner", lambda cid: None)  # 模擬 bob 檢查時還沒看到 alice 的寫入
    assert say(client, bob(), "me too", cid="shared-id").status_code == 404
    assert col.docs["shared-id"]["user_id"] == "alice"


def test_delete_removes_conversation_and_cache(client, mongo_store):
    store, _ = mongo_store
    cid = say(client, alice(), "bye").json()["conversation_id"]
    store.get_history(cid)
    assert client.delete(f"/conversations/{cid}", headers=alice()).json() == {"deleted": True}
    assert client.get(f"/conversations/{cid}", headers=alice()).status_code == 404
    assert not store._redis.exists("chat:" + cid)
    assert client.get("/conversations", headers=alice()).json()["conversations"] == []
    assert client.delete(f"/conversations/{cid}", headers=alice()).status_code == 404


def test_works_without_mongo_in_local_mode(client):
    cid = say(client, alice(), "local mode").json()["conversation_id"]
    assert client.get("/conversations", headers=alice()).json()["conversations"][0]["id"] == cid
    assert client.get(f"/conversations/{cid}", headers=bob()).status_code == 404
    assert client.delete(f"/conversations/{cid}", headers=alice()).status_code == 200


def test_mongo_failure_on_list_is_503(client, mongo_store):
    store, col = mongo_store
    store._col = type("Down", (), {"find": lambda *a, **k: (_ for _ in ()).throw(main.PyMongoError("down"))})()
    assert client.get("/conversations", headers=alice()).status_code == 503


def test_timestamps_are_utc_aware_even_if_mongo_returns_naive(client, mongo_store):
    """PyMongo 讀回的 datetime 沒有時區;API 必須補上,否則瀏覽器會把 UTC 當本地時間。"""
    from datetime import datetime
    store, col = mongo_store
    cid = say(client, alice(), "tz").json()["conversation_id"]
    doc = col.docs[cid]
    doc["updated_at"] = doc["updated_at"].replace(tzinfo=None)
    for m in doc["messages"]:
        m["ts"] = m["ts"].replace(tzinfo=None)
    listed = client.get("/conversations", headers=alice()).json()["conversations"][0]["updated_at"]
    full = client.get(f"/conversations/{cid}", headers=alice()).json()["messages"][0]["ts"]
    for value in (listed, full):
        assert datetime.fromisoformat(value).utcoffset().total_seconds() == 0
        assert value.endswith("+00:00")
