import { useEffect, useRef } from 'react'
import { AlertCircle, Menu, RotateCcw, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SUGGESTED_PROMPTS, type ChatStatus, type Conversation } from '@/lib/chat'
import { AssistantAvatar, MessageBubble } from './message-bubble'
import { ChatInput } from './chat-input'

type ChatWindowProps = {
  conversation: Conversation | null
  status: ChatStatus
  errorText: string | null
  historyLoading: boolean
  onSend: (text: string) => void
  onStop: () => void
  onRetry: () => void
  onOpenSidebar: () => void
}

function ThinkingIndicator() {
  return (
    <div className="flex gap-3" role="status" aria-label="Assistant is thinking">
      <AssistantAvatar />
      <div className="flex h-7 items-center gap-1">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="size-1.5 animate-bounce rounded-full bg-muted-foreground/70"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </div>
    </div>
  )
}

function ErrorMessage({ text, onRetry }: { text: string | null; onRetry: () => void }) {
  return (
    <div className="flex gap-3">
      <AssistantAvatar />
      <div
        role="alert"
        className="flex flex-1 flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3"
      >
        <div className="flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="size-4" aria-hidden="true" />
          {text ?? 'Something went wrong'}
        </div>
        <Button variant="outline" size="sm" onClick={onRetry} className="gap-1.5">
          <RotateCcw aria-hidden="true" />
          Retry
        </Button>
      </div>
    </div>
  )
}

function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-16 text-center">
      <div className="flex flex-col items-center gap-4">
        <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <Sparkles className="size-6" aria-hidden="true" />
        </div>
        <div className="flex flex-col gap-1.5">
          <h2 className="text-2xl font-semibold tracking-tight text-balance">How can I help you today?</h2>
          <p className="text-muted-foreground">Ask anything, or start with one of these.</p>
        </div>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTED_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => onPick(prompt)}
            className="rounded-full border bg-card px-4 py-2 text-sm shadow-sm transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  )
}

export function ChatWindow({
  conversation,
  status,
  errorText,
  historyLoading,
  onSend,
  onStop,
  onRetry,
  onOpenSidebar,
}: ChatWindowProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const messages = conversation?.messages ?? []

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, status])

  return (
    <main className="flex min-w-0 flex-1 flex-col bg-background">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b px-3 md:px-6">
        <Button
          variant="ghost"
          size="icon"
          onClick={onOpenSidebar}
          className="md:hidden"
          aria-label="Open sidebar"
        >
          <Menu />
        </Button>
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium">
          {conversation?.title ?? 'New chat'}
        </h1>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {historyLoading && messages.length === 0 ? (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground" role="status">
            Loading conversation…
          </div>
        ) : messages.length === 0 && status === 'idle' ? (
          <EmptyState onPick={onSend} />
        ) : (
          <div className="mx-auto flex w-full max-w-[720px] flex-col gap-8 px-4 py-8">
            {messages.map((message) => (
              <div key={message.id} className="flex flex-col gap-1.5">
                <MessageBubble message={message} />
                {message.stopped ? (
                  <p className="text-right text-xs text-muted-foreground">Response stopped.</p>
                ) : null}
              </div>
            ))}
            {status === 'loading' ? <ThinkingIndicator /> : null}
            {status === 'error' ? <ErrorMessage text={errorText} onRetry={onRetry} /> : null}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <div className="shrink-0 bg-gradient-to-t from-background via-background to-background/0 px-4 pt-2 pb-4">
        <div className="mx-auto w-full max-w-[720px]">
          <ChatInput isResponding={status === 'loading'} onSend={onSend} onStop={onStop} />
          <p className="mt-2 text-center text-xs text-muted-foreground">
            Enter to send, Shift+Enter for a new line. Replies come from Gemini and may be inaccurate.
          </p>
        </div>
      </div>
    </main>
  )
}
