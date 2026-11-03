import os
import re
import time
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from chat_store import ChatHistoryStore, DuplicateKeyError, PyMongoError
from llm_client import RetryPolicy, invoke_with_retry
from metrics import (
    LLM_LATENCY,
    LLM_REQUESTS,
    init_series,
    metrics_middleware,
    record_llm_usage,
    render_metrics,
)

# 本機:從 .env 讀值。在 cluster 裡沒有 .env(被 .dockerignore 排除),
# 這行不會做任何事,值由 K8s 注入。load_dotenv 預設不覆蓋已存在的環境變數。
load_dotenv()

# --- Config(必須放在 load_dotenv() 之後)---------------------------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
]

# 對話紀錄的長期儲存(Mongo = source of truth),細節都在 chat_store.py。
store = ChatHistoryStore.from_env()

# 對話記憶不再放在 pod 的記憶體裡(那樣無法水平擴展):
# 讀 = Redis 快取 → 沒有就讀 Mongo;寫 = 先 Mongo 再更新 Redis。細節見 chat_store.py。

app = FastAPI(title="Chatbot Backend")
app.middleware("http")(metrics_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- LLM setup -----------------------------------------------------------
# LangChain wraps the LLM call only — no agent / tool-calling layer, since
# this project doesn't need it. Using Gemini's free tier here (no credit
# card needed). Swap the import/model if you move to a different provider
# later — the rest of the app doesn't need to change.
llm = None
if os.getenv("FAKE_LLM", "").lower() == "true":
    # 演練/負載測試用的替身,見 fake_llm.py。不打 Gemini、不耗額度。
    from fake_llm import FakeLLM

    llm = FakeLLM.from_env()
elif os.getenv("GOOGLE_API_KEY"):
    from langchain_google_genai import ChatGoogleGenerativeAI

    # max_output_tokens:限制輸出長度(連同 reasoning token),是「歷史長度 + 輸出長度」兩道成本控制之一。
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        temperature=TEMPERATURE,
        max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "2048")),
        # SDK 預設 max_retries=6、timeout=None:關掉 SDK 重試、設單次逾時,重試改由 llm_client 統一管(見該檔說明)。
        max_retries=0,
        timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
    )


retry_policy = RetryPolicy.from_env()

# 啟動時印出設定,讓 kubectl logs -f 看得到(只印非敏感值,key 只印有沒有)
print(
    f"[startup] GEMINI_MODEL={GEMINI_MODEL} TEMPERATURE={TEMPERATURE} "
    f"CORS_ORIGINS={CORS_ORIGINS} GOOGLE_API_KEY_set={bool(os.getenv('GOOGLE_API_KEY'))} "
    f"MONGO_ENABLED={store.enabled} REDIS_ENABLED={store.cache_enabled} FAKE_LLM={type(llm).__name__ == 'FakeLLM'}",
    flush=True,
)
store.ensure_index()
init_series(GEMINI_MODEL)

# --- Schemas ---------------------------------------------------------------
class ChatRequest(BaseModel):
    # 已棄用:身分改由 X-User-Id header 提供。為了讓舊前端在換版期間還能用,沒帶 header 時才退回用這個欄位。
    user_id: Optional[str] = None
    message: str
    # 第一輪前端不帶,由後端產生 UUID 回傳;之後前端每輪都要帶回來。
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    user_id: str
    conversation_id: str
    reply: str


# --- 身分 ------------------------------------------------------------------
# 目前「身分」只是使用者自己輸入的名字(沒有密碼、沒有簽章),任何人輸入別人的名字就能看到他的對話——
# 這是刻意的範圍取捨(見 docs/design.md)。所有 API 都只透過 current_user() 取得身分,
# 日後換成 JWT / OAuth 只需要改這一個函式。
USER_ID_RE = re.compile(r"^[\w.@-]{1,64}$")


def current_user(header_value: Optional[str], fallback: Optional[str] = None) -> str:
    user_id = (header_value or fallback or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="missing X-User-Id")
    if not USER_ID_RE.match(user_id):
        raise HTTPException(status_code=422, detail="invalid user id")
    return user_id


def _store_call(fn, *args):
    """Mongo 失敗統一轉成 503(與 /chat 一致,指標上可和 502 的 LLM 失敗區分)。"""
    try:
        return fn(*args)
    except PyMongoError as e:
        print(f"[mongo] {getattr(fn, '__name__', 'call')} failed: {e}", flush=True)
        raise HTTPException(status_code=503, detail="conversation store unavailable")


# --- Routes ------------------------------------------------------------
@app.get("/health")
def health():
    """Used later for K8s liveness/readiness probes."""
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    """Prometheus 來這裡抓指標(pull 模型)。"""
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


def extract_text(content) -> str:
    """Newer models can return content as a string, or as a list of
    structured blocks (e.g. text blocks mixed with other block types).
    Normalize either shape down to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)
 
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, response: Response, x_user_id: Optional[str] = Header(None)):
    from langchain_core.messages import AIMessage, HumanMessage

    user_id = current_user(x_user_id, req.user_id)
    conversation_id = req.conversation_id or uuid.uuid4().hex
    if req.conversation_id:
        # 擁有者檢查要在讀快取「之前」:快取只用 conversation_id 當 key,先讀會繞過權限。
        # 不是自己的一律回 404(不是 403),避免洩漏「這個 id 存在」。
        owner = _store_call(store.get_owner, conversation_id)
        if owner is not None and owner != user_id:
            raise HTTPException(status_code=404, detail="conversation not found")
    stored = _store_call(store.get_history, conversation_id)
    history = [
        (HumanMessage if m["role"] == "user" else AIMessage)(content=m["content"])
        for m in stored
    ]

    # 診斷用 header:哪個 pod 回答、它「看到」幾則歷史。Day 9 用它抓到多 replica 記憶不一致;
    # Day 20 改用 Redis+Mongo 後,不管哪個 pod 回答,長度都該每輪 +2。
    response.headers["X-Served-By"] = os.getenv("HOSTNAME", "local")
    response.headers["X-History-Len"] = str(len(history))

    if llm is None:
        # No API key set yet — mock response so Day 1 Docker/K8s work isn't
        # blocked on having a real LLM key wired in. Replace once you reach
        # the Secret step (Day 5).
        reply = f"[mock reply] got: {req.message} (history={len(history)})"
    else:
        start = time.perf_counter()
        try:
            result = invoke_with_retry(llm, history + [HumanMessage(content=req.message)], retry_policy, GEMINI_MODEL)
        except Exception as e:
            # 外部依賴失敗(逾時、429 額度用完…)要被記下來,不能只剩一個 500。
            LLM_REQUESTS.labels(GEMINI_MODEL, "error").inc()
            LLM_LATENCY.labels(GEMINI_MODEL).observe(time.perf_counter() - start)
            print(f"[llm] call failed: {type(e).__name__}: {e}", flush=True)
            raise HTTPException(status_code=502, detail="llm call failed")
        LLM_REQUESTS.labels(GEMINI_MODEL, "ok").inc()
        LLM_LATENCY.labels(GEMINI_MODEL).observe(time.perf_counter() - start)
        record_llm_usage(GEMINI_MODEL, result.usage_metadata)
        # 只印用量摘要;原本 print(result) 會連同整串 thought signature 一起印出來。
        print(f"[llm] usage={result.usage_metadata}", flush=True)
        reply = extract_text(result.content)

    # 寫入順序固定「先寫 Mongo」——它是唯一的 source of truth,成功後才更新 Redis。
    # 寫失敗就回 503、快取不動,避免「使用者看到回覆但紀錄沒存」。
    try:
        store.append_turn(conversation_id, user_id, req.message, reply)
    except DuplicateKeyError:
        # 兩人同時搶同一個新 id、輸的那一方
        raise HTTPException(status_code=404, detail="conversation not found")
    except PyMongoError as e:
        print(f"[mongo] append_turn failed: {e}", flush=True)
        raise HTTPException(status_code=503, detail="conversation store unavailable")

    return ChatResponse(user_id=user_id, conversation_id=conversation_id, reply=reply)


@app.get("/conversations")
def list_conversations(x_user_id: Optional[str] = Header(None)):
    """這個使用者的對話列表(最近更新在前,最多 50 筆)。"""
    user_id = current_user(x_user_id)
    return {"user_id": user_id, "conversations": _store_call(store.list_conversations, user_id)}


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, x_user_id: Optional[str] = Header(None)):
    user_id = current_user(x_user_id)
    conv = _store_call(store.get_conversation, conversation_id, user_id)
    if conv is None:  # 不存在,或不是你的:一律 404
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, x_user_id: Optional[str] = Header(None)):
    user_id = current_user(x_user_id)
    if not _store_call(store.delete_conversation, conversation_id, user_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"deleted": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)