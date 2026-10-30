// REACT_APP_API_URL 是 CRA 的規則:build 時就會被烤進靜態檔案裡,
// 所以「換後端網址」在這個階段代表要重新 build image,不是改 runtime env。
// 之後接 Ingress(Day 6)可以改成同源 /api 反代,就不用管這件事了。
const API_BASE_URL = process.env.REACT_APP_API_URL || "http://api.chatbot.local";

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
