import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import {
  createId,
  filterConversations,
  titleFromMessage,
  type ChatStatus,
  type Conversation,
  type Message,
} from '@/lib/chat'
import {
  ApiError,
  deleteConversation,
  describeError,
  getMessages,
  listConversations,
  newConversationId,
  sendChat,
} from '@/lib/api'
import { applyTheme, getCurrentTheme, type Theme } from '@/lib/theme'
import { UserIdDialog } from './user-id-dialog'
import { Sidebar } from './sidebar'
import { ChatWindow } from './chat-window'
import { DeleteConversationDialog } from './delete-conversation-dialog'

const USER_STORAGE_KEY = 'userId'

function readStoredUser(): string | null {
  try {
    return localStorage.getItem(USER_STORAGE_KEY)
  } catch {
    return null
  }
}

function storeUser(id: string | null) {
  try {
    if (id) localStorage.setItem(USER_STORAGE_KEY, id)
    else localStorage.removeItem(USER_STORAGE_KEY)
  } catch {
    // 無法存取 storage(私密模式等):只是下次要重新輸入名字
  }
}

/** 所有聊天狀態都在這裡;資料來源是後端 API(src/lib/api.ts)。 */
export function ChatApp() {
  const [userId, setUserId] = useState<string | null>(readStoredUser)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [status, setStatus] = useState<ChatStatus>('idle')
  const [errorText, setErrorText] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [theme, setTheme] = useState<Theme | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // index.html 的 inline script 已在第一次繪製前套用主題,這裡只同步 state
    setTheme(getCurrentTheme())
    return () => controllerRef.current?.abort()
  }, [])

  const loadList = useCallback(async (id: string) => {
    setListError(null)
    try {
      setConversations(await listConversations(id))
    } catch (err) {
      setConversations([])
      setListError(err instanceof ApiError && err.status === 422 ? 'Invalid user ID' : 'Could not load chats')
    }
  }, [])

  // 重新整理頁面時,沿用上次輸入的名字並載入對話列表
  useEffect(() => {
    if (userId) void loadList(userId)
    // 只在第一次掛載時執行;之後登入由 handleLogin 觸發
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!userId) return
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSidebarOpen(true)
        searchInputRef.current?.focus()
        searchInputRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [userId])

  const visibleConversations = filterConversations(conversations, searchQuery)
  const activeConversation = conversations.find((c) => c.id === activeId) ?? null
  const pendingDelete = conversations.find((c) => c.id === pendingDeleteId) ?? null

  const updateConversation = (id: string, updater: (c: Conversation) => Conversation) =>
    setConversations((prev) => prev.map((c) => (c.id === id ? updater(c) : c)))

  const cancelPending = () => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setStatus('idle')
    setErrorText(null)
  }

  const startReply = async (conversationId: string, prompt: string) => {
    if (!userId) return
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setStatus('loading')
    setErrorText(null)

    try {
      const content = await sendChat(userId, conversationId, prompt, controller.signal)
      const reply: Message = { id: createId(), role: 'assistant', content, createdAt: Date.now() }
      updateConversation(conversationId, (c) => ({
        ...c,
        messages: [...c.messages, reply],
        updatedAt: reply.createdAt,
      }))
      setStatus('idle')
    } catch (err) {
      if (controller.signal.aborted) return
      setErrorText(describeError(err))
      setStatus('error')
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null
    }
  }

  const handleStop = () => {
    if (!controllerRef.current) return
    cancelPending()
    if (!activeId) return
    updateConversation(activeId, (c) => {
      const lastUserIndex = c.messages.findLastIndex((m) => m.role === 'user')
      if (lastUserIndex === -1) return c
      return { ...c, messages: c.messages.map((m, i) => (i === lastUserIndex ? { ...m, stopped: true } : m)) }
    })
  }

  const handleLogin = (id: string) => {
    cancelPending()
    storeUser(id)
    setUserId(id)
    setActiveId(null)
    setConversations([])
    void loadList(id)
  }

  const handleSwitchUser = () => {
    cancelPending()
    storeUser(null)
    setUserId(null)
    setActiveId(null)
    setConversations([])
    setListError(null)
    setSearchQuery('')
    setSidebarOpen(false)
  }

  const handleNewChat = () => {
    cancelPending()
    setActiveId(null)
    setSidebarOpen(false)
  }

  const handleSelect = async (id: string) => {
    if (id !== activeId) cancelPending()
    setActiveId(id)
    setSidebarOpen(false)

    const target = conversations.find((c) => c.id === id)
    if (!userId || !target || target.loaded) return
    setHistoryLoading(true)
    try {
      const messages = await getMessages(userId, id)
      updateConversation(id, (c) => ({ ...c, messages, loaded: true }))
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // 已在別處被刪除:從列表拿掉
        setConversations((prev) => prev.filter((c) => c.id !== id))
        setActiveId(null)
      } else {
        setErrorText(describeError(err))
        setStatus('error')
      }
    } finally {
      setHistoryLoading(false)
    }
  }

  const handleSend = (text: string) => {
    if (status === 'loading' || !userId) return
    const message: Message = { id: createId(), role: 'user', content: text, createdAt: Date.now() }

    if (activeConversation) {
      updateConversation(activeConversation.id, (c) => ({
        ...c,
        messages: [...c.messages, message],
        updatedAt: message.createdAt,
      }))
      void startReply(activeConversation.id, text)
    } else {
      const conversation: Conversation = {
        id: newConversationId(),
        title: titleFromMessage(text),
        messages: [message],
        updatedAt: message.createdAt,
        loaded: true,
      }
      setConversations((prev) => [conversation, ...prev])
      setActiveId(conversation.id)
      void startReply(conversation.id, text)
    }
  }

  const handleRetry = () => {
    const lastUser = activeConversation?.messages.findLast((m) => m.role === 'user')
    if (activeConversation && lastUser) void startReply(activeConversation.id, lastUser.content)
  }

  const handleConfirmDelete = async () => {
    const id = pendingDeleteId
    if (!id || !userId) return
    setPendingDeleteId(null)
    try {
      await deleteConversation(userId, id)
    } catch (err) {
      // 404 = 已經不存在,照樣從列表移除;其他錯誤保留項目
      if (!(err instanceof ApiError && err.status === 404)) {
        setListError(`Delete failed: ${describeError(err)}`)
        return
      }
    }
    if (id === activeId) {
      cancelPending()
      setActiveId(null)
    }
    setConversations((prev) => prev.filter((c) => c.id !== id))
  }

  const handleToggleTheme = () => {
    const next: Theme = getCurrentTheme() === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  return (
    <>
      <div
        inert={!userId}
        className={cn(
          'flex h-dvh overflow-hidden transition-[filter] duration-300',
          !userId && 'pointer-events-none blur-md select-none',
        )}
      >
        <Sidebar
          userId={userId}
          conversations={visibleConversations}
          activeId={activeId}
          open={sidebarOpen}
          theme={theme}
          searchQuery={searchQuery}
          searchInputRef={searchInputRef}
          listError={listError}
          onSearchChange={setSearchQuery}
          onClose={() => setSidebarOpen(false)}
          onNewChat={handleNewChat}
          onSelect={(id) => void handleSelect(id)}
          onRequestDelete={setPendingDeleteId}
          onSwitchUser={handleSwitchUser}
          onToggleTheme={handleToggleTheme}
        />
        <ChatWindow
          conversation={activeConversation}
          status={status}
          errorText={errorText}
          historyLoading={historyLoading}
          onSend={handleSend}
          onStop={handleStop}
          onRetry={handleRetry}
          onOpenSidebar={() => setSidebarOpen(true)}
        />
      </div>

      <UserIdDialog open={!userId} onSubmit={handleLogin} />
      <DeleteConversationDialog
        title={pendingDelete?.title ?? null}
        onCancel={() => setPendingDeleteId(null)}
        onConfirm={() => void handleConfirmDelete()}
      />
    </>
  )
}
