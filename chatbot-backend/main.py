import os
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from chat_store import ChatHistoryStore, PyMongoError

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
store = ChatHistoryStore()

# 記憶體版對話記憶:{conversation_id: [messages]}。
# 故意保留這個「不可水平擴展」的設計:每個 pod 各有一份,scale 到多個 replica 後
# 同一段對話打到不同 pod 就會失憶。Day 9 要親眼看到這個 bug,Day 20 用 Redis 修掉。
# 注意 Mongo 在這個階段只「寫」不「讀」,讀的修復留給 Day 20。
MEMORY_MAX_MESSAGES = 20
memory: dict[str, list] = {}

app = FastAPI(title="Chatbot Backend")
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
if os.getenv("GOOGLE_API_KEY"):
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=TEMPERATURE)

# 啟動時印出設定,讓 kubectl logs -f 看得到(只印非敏感值,key 只印有沒有)
print(
    f"[startup] GEMINI_MODEL={GEMINI_MODEL} TEMPERATURE={TEMPERATURE} "
    f"CORS_ORIGINS={CORS_ORIGINS} GOOGLE_API_KEY_set={bool(os.getenv('GOOGLE_API_KEY'))} "
    f"MONGO_ENABLED={store.enabled}",
    flush=True,
)
store.ensure_index()

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
    history = memory.get(conversation_id, [])

    # 診斷用 header:哪個 pod 回答、它「看到」幾則歷史。Day 9 用來證明多 replica
    # 時記憶不一致(同一段對話打到不同 pod,history 長度會忽然歸零)。
    response.headers["X-Served-By"] = os.getenv("HOSTNAME", "local")
    response.headers["X-History-Len"] = str(len(history))

    if llm is None:
        # No API key set yet — mock response so Day 1 Docker/K8s work isn't
        # blocked on having a real LLM key wired in. Replace once you reach
        # the Secret step (Day 5).
        reply = f"[mock reply] got: {req.message} (history={len(history)})"
    else:
        result = llm.invoke(history + [HumanMessage(content=req.message)])
        print(result)
        reply = extract_text(result.content)

    # 寫入順序固定「先寫 Mongo」——它是唯一的 source of truth。
    # 寫失敗就回 503、不更新記憶體,避免「使用者看到回覆但紀錄沒存」。
    try:
        store.append_turn(conversation_id, req.user_id, req.message, reply)
    except PyMongoError as e:
        print(f"[mongo] append_turn failed: {e}", flush=True)
        raise HTTPException(status_code=503, detail="conversation store unavailable")

    memory[conversation_id] = (
        history + [HumanMessage(content=req.message), AIMessage(content=reply)]
    )[-MEMORY_MAX_MESSAGES:]
    return ChatResponse(
        user_id=req.user_id, conversation_id=conversation_id, reply=reply
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)