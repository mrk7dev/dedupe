interface FolderSelectButtonProps {
  label: string
  paths: string[]
  onAdd: () => void
  onRemove: (path: string) => void
}

export function FolderSelectButton({ label, paths, onAdd, onRemove }: FolderSelectButtonProps) {
  return (
    <div className="flex-1 rounded-lg border border-neutral-200 bg-white p-3 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="text-xs font-medium tracking-wide text-neutral-500 uppercase">{label}</div>
      <div className="mt-1.5 flex flex-col gap-1">
        {paths.length === 0 && <span className="font-mono text-xs text-neutral-500">nothing selected</span>}
        {paths.map((path) => (
          <div
            key={path}
            className="flex items-center gap-2 rounded-md bg-neutral-50 px-2 py-1 dark:bg-neutral-800/60"
          >
            <span className="min-w-0 flex-1 truncate font-mono text-xs text-neutral-600 dark:text-neutral-400">
              {path}
            </span>
            <button
              onClick={() => onRemove(path)}
              aria-label={`Remove ${path}`}
              className="shrink-0 rounded text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
            >
              ×
            </button>
          </div>
        ))}
        <button
          onClick={onAdd}
          className="mt-1 self-start rounded-md border border-neutral-300 px-2.5 py-1 text-xs font-medium hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          Add folder…
        </button>
      </div>
    </div>
  )
}
