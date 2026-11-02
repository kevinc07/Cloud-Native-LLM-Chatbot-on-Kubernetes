import os
import time
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from chat_store import ChatHistoryStore, PyMongoError
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
    )

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
    user_id: str
    message: str
    # 第一輪前端不帶,由後端產生 UUID 回傳;之後前端每輪都要帶回來。
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    user_id: str
    conversation_id: str
    reply: str


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
def chat(req: ChatRequest, response: Response):
    from langchain_core.messages import AIMessage, HumanMessage

    conversation_id = req.conversation_id or uuid.uuid4().hex
    try:
        stored = store.get_history(conversation_id)
    except PyMongoError as e:
        print(f"[mongo] get_history failed: {e}", flush=True)
        raise HTTPException(status_code=503, detail="conversation store unavailable")
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
            result = llm.invoke(history + [HumanMessage(content=req.message)])
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
        store.append_turn(conversation_id, req.user_id, req.message, reply)
    except PyMongoError as e:
        print(f"[mongo] append_turn failed: {e}", flush=True)
        raise HTTPException(status_code=503, detail="conversation store unavailable")

    return ChatResponse(
        user_id=req.user_id, conversation_id=conversation_id, reply=reply
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)