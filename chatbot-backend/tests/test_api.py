import main
from conftest import BrokenLLM


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_chat_without_llm_returns_mock_and_new_conversation_id(client):
    r = client.post("/chat", json={"user_id": "u1", "message": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1"
    assert body["conversation_id"]  # 後端產生
    assert body["reply"].startswith("[mock reply]")


def test_chat_missing_message_is_422(client):
    assert client.post("/chat", json={"user_id": "u1"}).status_code == 422


def test_chat_remembers_history_within_a_conversation(client, stub_llm):
    first = client.post("/chat", json={"user_id": "u1", "message": "one"}).json()
    cid = first["conversation_id"]
    r = client.post(
        "/chat", json={"user_id": "u1", "message": "two", "conversation_id": cid}
    )
    assert r.headers["X-History-Len"] == "2"  # 第二輪看得到第一輪的 user+bot
    # 第二次呼叫 LLM 時,送出的訊息 = 2 則歷史 + 這次的問題
    assert len(stub_llm.calls[1]) == 3


def test_conversations_are_isolated(client, stub_llm):
    a = client.post("/chat", json={"user_id": "u1", "message": "a"}).json()
    b = client.post("/chat", json={"user_id": "u2", "message": "b"}).json()
    assert a["conversation_id"] != b["conversation_id"]
    assert len(stub_llm.calls[1]) == 1  # b 的對話沒有混進 a 的歷史


def test_memory_is_capped(client, stub_llm):
    cid = None
    for i in range(main.MEMORY_MAX_MESSAGES):  # 每輪 +2 則,必然超過上限
        body = {"user_id": "u", "message": f"m{i}"}
        if cid:
            body["conversation_id"] = cid
        cid = client.post("/chat", json=body).json()["conversation_id"]
    assert len(main.memory[cid]) == main.MEMORY_MAX_MESSAGES


def test_llm_failure_becomes_502_and_is_not_remembered(client, monkeypatch):
    monkeypatch.setattr(main, "llm", BrokenLLM())
    r = client.post(
        "/chat", json={"user_id": "u1", "message": "hi", "conversation_id": "c1"}
    )
    assert r.status_code == 502
    assert "c1" not in main.memory  # 失敗的一輪不能留在記憶裡


def test_mongo_failure_becomes_503(client, stub_llm, monkeypatch):
    class DownStore:
        enabled = True

        def append_turn(self, *a, **k):
            raise main.PyMongoError("down")

    monkeypatch.setattr(main, "store", DownStore())
    r = client.post(
        "/chat", json={"user_id": "u1", "message": "hi", "conversation_id": "c1"}
    )
    assert r.status_code == 503
    assert "c1" not in main.memory  # 沒存進 Mongo 就不能更新記憶體


def test_extract_text_handles_block_lists():
    blocks = [{"type": "text", "text": "a"}, {"type": "thinking"}, "b"]
    assert main.extract_text(blocks) == "ab"
    assert main.extract_text("plain") == "plain"
