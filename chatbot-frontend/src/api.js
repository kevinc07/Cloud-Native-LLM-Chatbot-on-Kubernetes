// 預設用「同源」(空字串 = 呼叫網頁自己所在的網址):Ingress 把 /chat、/health 分流到 backend,
// 所以部署後不用把任何網址烤進 image,換網址也不用重新 build。
// 本機開發才需要設 REACT_APP_API_URL(見 .env.example);CRA 規則:它會在 build 時被烤進靜態檔案。
const API_BASE_URL = process.env.REACT_APP_API_URL ?? "";

export async function checkHealth() {
  const res = await fetch(`${API_BASE_URL}/health`);
  if (!res.ok) {
    throw new Error(`health check failed: ${res.status}`);
  }
  return res.json();
}

export async function sendMessage(userId, message, conversationId) {
  // user_id 目前是前端信任傳入、後端沒有驗證(調整版 Day1 就講明這是刻意
  // 簡化,Day25-26 要誠實寫進 README)。這裡先老實對應這個設計,不假裝有登入。
  const res = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // 第一輪 conversationId 是 null,後端會產生 UUID 回傳;之後每輪都要帶回去。
    body: JSON.stringify({
      user_id: userId,
      message,
      conversation_id: conversationId || null,
    }),
  });
  if (!res.ok) {
    throw new Error(`chat request failed: ${res.status}`);
  }
  return res.json();
}
