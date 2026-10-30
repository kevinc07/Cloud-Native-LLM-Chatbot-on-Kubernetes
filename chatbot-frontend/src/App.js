import { useEffect, useState } from "react";
import "./App.css";
import { checkHealth, sendMessage } from "./api";

function App() {
  const [backendStatus, setBackendStatus] = useState("checking...");
  // 沒有真的登入系統(刻意簡化,詳見 Day25-26 README),這裡就讓使用者
  // 自己打一個名字當 user_id,純粹是為了 Day9 能開兩個分頁、
  // 用不同 user_id 同時測「多 replica 時記憶體版本記憶時有時無」那個 bug。
  const [userId, setUserId] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [sending, setSending] = useState(false);
  // 一個 user 可以有多段對話,所以資料以 conversation_id 為主鍵,不是 user_id。
  // 第一輪是 null,由後端產生後回傳。
  const [conversationId, setConversationId] = useState(null);

  function handleNewConversation() {
    setConversationId(null);
    setMessages([]);
  }

  useEffect(() => {
    checkHealth()
      .then(() => setBackendStatus("ok"))
      .catch(() => setBackendStatus("unreachable"));
  }, []);

  async function handleSend(e) {
    e.preventDefault();
    if (!input.trim() || !userId.trim() || sending) return;

    const userMsg = input;
    setMessages((prev) => [...prev, { role: "user", text: userMsg }]);
    setInput("");
    setSending(true);

    try {
      // 注意:欄位名稱要對到你 Day1 main.py 裡 /chat 實際的 request/response
      // schema。這裡先假設 request 是 {user_id, message}、response 是
      // {reply},跟你的 pydantic model 對不上的話改這裡跟 api.js 就好。
      const data = await sendMessage(userId, userMsg, conversationId);
      if (data.conversation_id) setConversationId(data.conversation_id);
      setMessages((prev) => [
        ...prev,
        { role: "bot", text: data.reply ?? JSON.stringify(data) },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "bot", text: `[error] ${err.message}` },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Chatbot Frontend</h1>
        <span className={`status status-${backendStatus}`}>
          backend: {backendStatus}
        </span>
      </header>

      <div className="user-id-bar">
        <label htmlFor="userId">user_id(沒有登入系統,自己打一個名字)</label>
        <input
          id="userId"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          placeholder="例如 alice"
        />
      </div>

      <div className="user-id-bar">
        <span>conversation_id: {conversationId ?? "(新對話,送出第一則後產生)"}</span>
        <button type="button" onClick={handleNewConversation}>
          新對話
        </button>
      </div>

      <div className="chat-window">
        {messages.length === 0 && (
          <p className="empty-hint">Day 2 checkpoint: 這頁能打開,且能打到 backend 就算過。</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`bubble bubble-${m.role}`}>
            {m.text}
          </div>
        ))}
      </div>

      <form className="chat-form" onSubmit={handleSend}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="輸入訊息..."
          disabled={sending || !userId.trim()}
        />
        <button type="submit" disabled={sending || !userId.trim()}>
          {sending ? "送出中..." : "送出"}
        </button>
      </form>
    </div>
  );
}

export default App;
