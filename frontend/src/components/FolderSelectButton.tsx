interface FolderSelectButtonProps {
  label: string
  path: string | null
  onClick: () => void
}

export function FolderSelectButton({ label, path, onClick }: FolderSelectButtonProps) {
  return (
    <div className="flex-1 rounded-lg border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="text-xs font-medium tracking-wide text-neutral-500 uppercase">{label}</div>
      <div className="mt-1 flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-neutral-600 dark:text-neutral-400">
          {path ?? 'nothing selected'}
        </span>
        <button
          onClick={onClick}
          className="shrink-0 rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          {path ? 'Change…' : 'Select folder…'}
        </button>
      </div>
    </div>
  )
}
