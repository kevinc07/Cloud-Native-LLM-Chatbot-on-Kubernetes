// 後端 API。部署後前端與 API 同源(Ingress 依路徑分流),所以 base URL 是空字串;
// 本機開發由 vite.config.ts 的 proxy 轉給後端。
//
// 身分:只是使用者自己輸入的名字,放在 X-User-Id header(後端 current_user() 讀它)。
// 沒有密碼或簽章,這是刻意的範圍取捨,見 docs/design.md。
import type { Conversation, Message } from '@/lib/chat'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(userId: string, path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-User-Id': userId, ...init.headers },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      // Ingress 擋下的請求(例如限流 503)回的是 HTML,不是 JSON
    }
    throw new ApiError(res.status, String(detail))
  }
  return res.json() as Promise<T>
}

type ServerMessage = { role: 'user' | 'assistant'; content: string; ts: string | null }
type ServerConversationSummary = { id: string; title: string; updated_at: string | null }

const toMillis = (iso: string | null) => (iso ? Date.parse(iso) : Date.now())

export async function listConversations(userId: string): Promise<Conversation[]> {
  const data = await request<{ conversations: ServerConversationSummary[] }>(userId, '/conversations')
  // 列表只有摘要;訊息等點進去才載入(loaded=false)
  return data.conversations.map((c) => ({
    id: c.id,
    title: c.title,
    updatedAt: toMillis(c.updated_at),
    messages: [],
    loaded: false,
  }))
}

export async function getMessages(userId: string, conversationId: string): Promise<Message[]> {
  const data = await request<{ messages: ServerMessage[] }>(
    userId,
    `/conversations/${encodeURIComponent(conversationId)}`,
  )
  return data.messages.map((m, i) => ({
    id: `${conversationId}-${i}`,
    role: m.role,
    content: m.content,
    createdAt: toMillis(m.ts),
  }))
}

export async function deleteConversation(userId: string, conversationId: string): Promise<void> {
  await request(userId, `/conversations/${encodeURIComponent(conversationId)}`, { method: 'DELETE' })
}

/**
 * 送出一則訊息並等待回覆。signal 被 abort(使用者按 Stop)時,fetch 會丟出 AbortError。
 * 注意:這只是「前端不等了」;後端那次 Gemini 呼叫仍會跑完並存進 Mongo(已知限制)。
 */
export async function sendChat(
  userId: string,
  conversationId: string,
  message: string,
  signal: AbortSignal,
): Promise<string> {
  const data = await request<{ reply: string }>(userId, '/chat', {
    method: 'POST',
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  })
  return data.reply
}

/**
 * 新對話的 id 由前端產生(32 位 hex,與後端 uuid4().hex 同格式),第一則訊息就帶上。
 * 好處:使用者按 Stop 後再送,後端仍寫進同一段對話,不會多出一段看不到的對話。
 * 不用 crypto.randomUUID():它只在 https / localhost 可用,而部署的網址是 http。
 */
export function newConversationId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 502) return 'The AI model failed to respond. Please try again.'
    if (err.status === 503) return 'The service is busy or temporarily unavailable. Please wait a moment and retry.'
    if (err.status === 404) return 'This conversation no longer exists.'
    return `Request failed (${err.status}).`
  }
  return 'Network error. Check your connection and retry.'
}
