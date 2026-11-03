import { MessageSquare, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatRelativeTime, groupConversations, type Conversation } from '@/lib/chat'

type ConversationListProps = {
  conversations: Conversation[]
  activeId: string | null
  onSelect: (id: string) => void
  onRequestDelete: (id: string) => void
  emptyMessage?: string
}

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onRequestDelete,
  emptyMessage = 'No conversations yet',
}: ConversationListProps) {
  if (conversations.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
        <div className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <MessageSquare className="size-4" aria-hidden="true" />
        </div>
        <p className="text-sm text-muted-foreground">{emptyMessage}</p>
      </div>
    )
  }

  const groups = groupConversations(conversations)

  return (
    <nav aria-label="Conversations" className="flex flex-col gap-5">
      {groups.map((group) => (
        <section key={group.label} className="flex flex-col gap-0.5">
          <h2 className="px-3 pb-1 text-xs font-medium text-muted-foreground">{group.label}</h2>
          <ul className="flex flex-col gap-0.5">
            {group.items.map((conversation) => {
              const isActive = conversation.id === activeId
              return (
                <li key={conversation.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(conversation.id)}
                    aria-current={isActive ? 'page' : undefined}
                    className={cn(
                      'flex w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2 pr-10 text-left transition-colors',
                      isActive
                        ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                        : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60',
                    )}
                  >
                    <span className="w-full truncate text-sm font-medium">{conversation.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {formatRelativeTime(conversation.updatedAt)}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onRequestDelete(conversation.id)}
                    aria-label={`Delete conversation "${conversation.title}"`}
                    className="absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-background hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100 max-md:opacity-100"
                  >
                    <Trash2 className="size-3.5" aria-hidden="true" />
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </nav>
  )
}
