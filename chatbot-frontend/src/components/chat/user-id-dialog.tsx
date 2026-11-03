import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

type UserIdDialogProps = {
  open: boolean
  onSubmit: (userId: string) => void
}

export function UserIdDialog({ open, onSubmit }: UserIdDialogProps) {
  const [value, setValue] = useState('')
  const trimmed = value.trim()
  // 與後端 USER_ID_RE 相同:字母數字、底線、. @ -,最多 64 字
  const valid = /^[\p{L}\p{N}_.@-]{1,64}$/u.test(trimmed)

  return (
    <Dialog open={open} disablePointerDismissal>
      <DialogContent showCloseButton={false} className="gap-6 p-6 shadow-xl sm:max-w-md">
        <DialogHeader className="items-start gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Sparkles className="size-5" aria-hidden="true" />
          </div>
          <DialogTitle className="text-xl font-semibold">Welcome</DialogTitle>
          <DialogDescription className="text-pretty leading-relaxed">
            Enter a user ID to continue. Your conversations are saved under this ID.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (valid) {
              onSubmit(trimmed)
              setValue('')
            }
          }}
        >
          <label htmlFor="user-id" className="sr-only">
            User ID
          </label>
          <Input
            id="user-id"
            autoFocus
            autoComplete="off"
            placeholder="e.g. alice"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="h-11 rounded-xl px-3.5"
          />
          {trimmed && !valid ? (
            <p className="text-xs text-destructive">
              Use letters, numbers, and _ . @ - only (max 64 characters).
            </p>
          ) : null}
          <Button type="submit" disabled={!valid} className="h-11 rounded-xl">
            Continue
          </Button>
        </form>

        <p className="text-xs text-muted-foreground">
          No password: anyone who enters the same ID sees the same chats. Demo only.
        </p>
      </DialogContent>
    </Dialog>
  )
}
