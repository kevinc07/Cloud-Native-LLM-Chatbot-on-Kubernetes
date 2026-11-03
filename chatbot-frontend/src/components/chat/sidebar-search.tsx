import type { Ref } from 'react'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/ui/input'

type SidebarSearchProps = {
  value: string
  onChange: (value: string) => void
  inputRef?: Ref<HTMLInputElement>
}

export function SidebarSearch({ value, onChange, inputRef }: SidebarSearchProps) {
  return (
    <div className="relative">
      <label htmlFor="sidebar-search" className="sr-only">
        Search chats
      </label>
      <Search
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <Input
        ref={inputRef}
        id="sidebar-search"
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && value) {
            e.preventDefault()
            onChange('')
          }
        }}
        placeholder="Search chats"
        autoComplete="off"
        aria-keyshortcuts="Meta+K Control+K"
        className="h-9 rounded-lg bg-background pr-8 pl-9"
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange('')}
          aria-label="Clear search"
          className="absolute top-1/2 right-1.5 flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <X className="size-3.5" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  )
}
