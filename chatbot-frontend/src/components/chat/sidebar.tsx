import { LogOut, Moon, Plus, Sparkles, Sun, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Ref } from 'react'
import type { Conversation } from '@/lib/chat'
import type { Theme } from '@/lib/theme'
import { ConversationList } from './conversation-list'
import { SidebarSearch } from './sidebar-search'

type SidebarProps = {
  userId: string | null
  conversations: Conversation[]
  activeId: string | null
  open: boolean
  theme: Theme | null
  searchQuery: string
  searchInputRef?: Ref<HTMLInputElement>
  /** 載入或刪除失敗的訊息,顯示在列表位置 */
  listError?: string | null
  onSearchChange: (value: string) => void
  onClose: () => void
  onNewChat: () => void
  onSelect: (id: string) => void
  onRequestDelete: (id: string) => void
  onSwitchUser: () => void
  onToggleTheme: () => void
}

export function Sidebar({
  userId,
  conversations,
  activeId,
  open,
  theme,
  searchQuery = '',
  searchInputRef,
  listError,
  onSearchChange,
  onClose,
  onNewChat,
  onSelect,
  onRequestDelete,
  onSwitchUser,
  onToggleTheme,
}: SidebarProps) {
  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          'fixed inset-0 z-30 bg-black/30 backdrop-blur-[2px] transition-opacity md:hidden',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground shadow-xl transition-transform duration-200 md:static md:translate-x-0 md:shadow-none',
          open ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex items-center justify-between px-4 pt-4 pb-3">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Sparkles className="size-3.5" aria-hidden="true" />
            </div>
            <span className="font-semibold tracking-tight">AI Chatbot</span>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onClose}
            className="md:hidden"
            aria-label="Close sidebar"
          >
            <X />
          </Button>
        </div>

        <div className="flex flex-col gap-2 px-3 pb-2">
          <Button onClick={onNewChat} className="h-10 w-full justify-start gap-2 rounded-xl shadow-sm">
            <Plus aria-hidden="true" />
            New chat
          </Button>
          <SidebarSearch value={searchQuery} onChange={onSearchChange} inputRef={searchInputRef} />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {listError && conversations.length > 0 ? (
            <p role="alert" className="px-3 pb-2 text-xs text-destructive">
              {listError}
            </p>
          ) : null}
          <ConversationList
            conversations={conversations}
            activeId={activeId}
            onSelect={onSelect}
            onRequestDelete={onRequestDelete}
            emptyMessage={listError ?? (searchQuery.trim() ? 'No matching chats' : undefined)}
          />
        </div>

        <div className="flex flex-col gap-2 border-t border-sidebar-border p-3">
          <div className="flex items-center gap-3 rounded-xl px-2 py-1.5">
            <div
              aria-hidden="true"
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold uppercase text-primary"
            >
              {userId?.charAt(0) ?? '?'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted-foreground">Signed in as</p>
              <p className="truncate text-sm font-medium">{userId ?? '—'}</p>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onToggleTheme}
              aria-label={
                theme === null ? 'Toggle theme' : theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
              }
            >
              {/* Icon follows the <html> class via CSS so it is correct on first paint. */}
              <Sun className="hidden dark:block" />
              <Moon className="dark:hidden" />
            </Button>
          </div>
          <Button variant="outline" size="sm" onClick={onSwitchUser} className="h-8 w-full gap-2 rounded-lg">
            <LogOut aria-hidden="true" />
            Switch user
          </Button>
        </div>
      </aside>
    </>
  )
}
