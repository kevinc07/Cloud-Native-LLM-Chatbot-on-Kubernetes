import { FileText, ImageIcon, X } from 'lucide-react'
import { formatFileSize } from '@/lib/chat'

type FileChipsProps = {
  files: File[]
  onRemove: (index: number) => void
}

export function FileChips({ files, onRemove }: FileChipsProps) {
  return (
    <ul className="flex flex-wrap gap-2 px-1 pt-1" aria-label="Attached files">
      {files.map((file, index) => {
        const Icon = file.type.startsWith('image/') ? ImageIcon : FileText
        return (
          <li
            key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
            className="flex max-w-full items-center gap-2 rounded-lg border bg-muted/60 py-1 pr-1 pl-2 text-xs"
          >
            <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="max-w-40 truncate font-medium" title={file.name}>
              {file.name}
            </span>
            <span className="shrink-0 text-muted-foreground">{formatFileSize(file.size)}</span>
            <button
              type="button"
              onClick={() => onRemove(index)}
              aria-label={`Remove ${file.name}`}
              className="flex size-5 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <X className="size-3" aria-hidden="true" />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
