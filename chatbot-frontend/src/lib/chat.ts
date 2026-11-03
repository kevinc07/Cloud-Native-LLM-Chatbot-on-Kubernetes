export type Role = 'user' | 'assistant'

export type Message = {
  id: string
  role: Role
  content: string
  createdAt: number
  /** Set on a user message whose reply was cancelled with Stop. */
  stopped?: boolean
}

export type Conversation = {
  id: string
  title: string
  messages: Message[]
  updatedAt: number
  /** 列表只有摘要;false 代表訊息還沒從後端載入 */
  loaded: boolean
}

export type ChatStatus = 'idle' | 'loading' | 'error'

const HOUR = 60 * 60 * 1000
const DAY = 24 * HOUR

export function createId() {
  return Math.random().toString(36).slice(2, 10)
}

// 與後端 chat_store._make_title 相同規則(30 字),新對話在本地顯示的標題與重新整理後一致
export function titleFromMessage(text: string) {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > 30 ? `${clean.slice(0, 30)}…` : clean || 'New chat'
}

export function formatRelativeTime(timestamp: number, now = Date.now()) {
  const diff = Math.max(0, now - timestamp)
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** Client-side title search. Swap this for a server-side search call later. */
export function filterConversations(conversations: Conversation[], query: string) {
  const needle = query.trim().toLowerCase()
  if (!needle) return conversations
  return conversations.filter((c) => c.title.toLowerCase().includes(needle))
}

export function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let size = bytes / 1024
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit++
  }
  return `${size < 10 ? size.toFixed(1) : Math.round(size)} ${units[unit]}`
}

export type ConversationGroup = { label: 'Today' | 'Yesterday' | 'Earlier'; items: Conversation[] }

export function groupConversations(conversations: Conversation[], now = Date.now()): ConversationGroup[] {
  const startOfToday = new Date(now)
  startOfToday.setHours(0, 0, 0, 0)
  const todayStart = startOfToday.getTime()
  const yesterdayStart = todayStart - DAY

  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt)
  const groups: ConversationGroup[] = [
    { label: 'Today', items: sorted.filter((c) => c.updatedAt >= todayStart) },
    {
      label: 'Yesterday',
      items: sorted.filter((c) => c.updatedAt < todayStart && c.updatedAt >= yesterdayStart),
    },
    { label: 'Earlier', items: sorted.filter((c) => c.updatedAt < yesterdayStart) },
  ]
  return groups.filter((g) => g.items.length > 0)
}

export const SUGGESTED_PROMPTS = [
  'Explain React hooks in simple terms',
  'Write a Python function to reverse a string',
  'Give me 3 ideas for a weekend project',
]
