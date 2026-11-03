import { Sparkles } from 'lucide-react'
import type { Message } from '@/lib/chat'

type Segment = { type: 'text'; content: string } | { type: 'code'; content: string; lang: string }

function parseContent(content: string): Segment[] {
  const segments: Segment[] = []
  const pattern = /```(\w*)\n?([\s\S]*?)```/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(content)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'text', content: content.slice(lastIndex, match.index) })
    }
    segments.push({ type: 'code', lang: match[1], content: match[2].replace(/\n$/, '') })
    lastIndex = pattern.lastIndex
  }
  if (lastIndex < content.length) segments.push({ type: 'text', content: content.slice(lastIndex) })
  return segments
}

export function AssistantAvatar() {
  return (
    <div
      aria-hidden="true"
      className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm"
    >
      <Sparkles className="size-3.5" />
    </div>
  )
}

export function MessageBubble({ message }: { message: Message }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-[15px] leading-relaxed text-secondary-foreground">
          <span className="sr-only">You: </span>
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-3">
      <AssistantAvatar />
      <div className="flex min-w-0 flex-1 flex-col gap-3 text-[15px] leading-relaxed">
        <span className="sr-only">Assistant: </span>
        {parseContent(message.content).map((segment, i) =>
          segment.type === 'code' ? (
            <figure key={i} className="overflow-hidden rounded-xl border bg-muted/60">
              {segment.lang ? (
                <figcaption className="border-b px-3 py-1.5 font-mono text-xs text-muted-foreground">
                  {segment.lang}
                </figcaption>
              ) : null}
              <pre className="overflow-x-auto p-3.5 font-mono text-[13px] leading-relaxed">
                <code>{segment.content}</code>
              </pre>
            </figure>
          ) : (
            <p key={i} className="whitespace-pre-wrap text-pretty">
              {segment.content.trim()}
            </p>
          ),
        )}
      </div>
    </div>
  )
}
