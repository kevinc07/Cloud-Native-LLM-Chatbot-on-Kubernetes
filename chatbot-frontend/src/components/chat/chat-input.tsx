import { useState } from 'react'
import { ArrowUp, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AttachMenu } from './attach-menu'
import { FileChips } from './file-chips'

type ChatInputProps = {
  isResponding: boolean
  onSend: (text: string) => void
  onStop: () => void
}

export function ChatInput({ isResponding, onSend, onStop }: ChatInputProps) {
  const [value, setValue] = useState('')
  const [files, setFiles] = useState<File[]>([])
  // 後端還不收檔案:有附檔時不讓送出並提示,避免檔案被默默丟掉(「+」選單是之後擴充功能的預留位置)
  const uploadsBlocked = files.length > 0
  const canSend = !isResponding && !uploadsBlocked && value.trim().length > 0

  const submit = () => {
    if (!canSend) return
    onSend(value.trim())
    setValue('')
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      className="flex flex-col gap-1.5 rounded-3xl border bg-card p-2 shadow-lg shadow-black/5 transition-colors focus-within:border-ring dark:shadow-black/30"
    >
      {files.length > 0 ? (
        <>
          <FileChips files={files} onRemove={(index) => setFiles((prev) => prev.filter((_, i) => i !== index))} />
          <p role="status" className="px-2 text-xs text-muted-foreground">
            File upload isn't available yet. Remove the attachments to send.
          </p>
        </>
      ) : null}

      <div className="flex items-end gap-1">
        <AttachMenu onFilesSelected={(picked) => setFiles((prev) => [...prev, ...picked])} />
        <label htmlFor="chat-input" className="sr-only">
          Message
        </label>
        <textarea
          id="chat-input"
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              if (e.nativeEvent.isComposing || e.keyCode === 229) return
              e.preventDefault()
              submit()
            }
          }}
          placeholder="Message AI Chatbot…"
          className="field-sizing-content max-h-48 min-h-6 min-w-0 flex-1 resize-none self-center bg-transparent px-1 py-1.5 text-[15px] leading-6 outline-none placeholder:text-muted-foreground"
        />
        {isResponding ? (
          <Button
            key="stop"
            type="button"
            size="icon-lg"
            onClick={onStop}
            className="shrink-0 rounded-full"
            aria-label="Stop generating"
          >
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            key="send"
            type="submit"
            size="icon-lg"
            disabled={!canSend}
            className="shrink-0 rounded-full"
            aria-label="Send message"
          >
            <ArrowUp />
          </Button>
        )}
      </div>
    </form>
  )
}
