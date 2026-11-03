import { useEffect, useId, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { ImageIcon, Paperclip, Plus, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type AttachMenuProps = {
  onFilesSelected: (files: File[]) => void
}

function MenuItem({
  icon,
  children,
  disabled,
  onSelect,
}: {
  icon: ReactNode
  children: ReactNode
  disabled?: boolean
  onSelect?: () => void
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      aria-disabled={disabled}
      onClick={onSelect}
      className={cn(
        'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm outline-none transition-colors [&_svg]:size-4 [&_svg]:shrink-0',
        disabled
          ? 'cursor-not-allowed text-muted-foreground'
          : 'hover:bg-accent focus-visible:bg-accent [&_svg]:text-muted-foreground',
      )}
    >
      {icon}
      {children}
    </button>
  )
}

export function AttachMenu({ onFilesSelected }: AttachMenuProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()

    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const openPicker = (input: HTMLInputElement | null) => {
    setOpen(false)
    input?.click()
  }

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) onFilesSelected(files)
    e.target.value = ''
  }

  return (
    <div ref={rootRef} className="relative shrink-0">
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="icon-lg"
        onClick={() => setOpen((v) => !v)}
        aria-label="Add attachment"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        className={cn('rounded-full text-muted-foreground', open && 'bg-accent text-foreground')}
      >
        <Plus className={cn('size-5 transition-transform duration-200', open && 'rotate-45')} />
      </Button>

      {open ? (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label="Attachment options"
          className="absolute bottom-full left-0 z-20 mb-3 flex w-52 flex-col gap-0.5 rounded-xl border bg-popover p-1 text-popover-foreground shadow-lg shadow-black/10 animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 dark:shadow-black/40"
        >
          <MenuItem icon={<Paperclip aria-hidden="true" />} onSelect={() => openPicker(fileInputRef.current)}>
            Upload file
          </MenuItem>
          <MenuItem icon={<ImageIcon aria-hidden="true" />} onSelect={() => openPicker(imageInputRef.current)}>
            Upload image
          </MenuItem>
          <div role="separator" className="my-1 h-px bg-border" />
          <MenuItem icon={<Sparkles aria-hidden="true" />} disabled>
            More coming soon
          </MenuItem>
        </div>
      ) : null}

      <input ref={fileInputRef} type="file" multiple hidden tabIndex={-1} onChange={handleChange} />
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        tabIndex={-1}
        onChange={handleChange}
      />
    </div>
  )
}
