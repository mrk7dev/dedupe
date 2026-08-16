import type { CompareProgress } from '../types'

const PHASE_LABEL: Record<CompareProgress['phase'], string> = {
  idle: 'Idle',
  counting: 'Counting files…',
  scanning: 'Walking folders…',
  hashing: 'Hashing content…',
  ready: 'Done',
  error: 'Error',
  cancelled: 'Cancelled',
}

function splitPath(path: string): { folder: string; name: string } {
  const idx = path.lastIndexOf('/')
  return idx === -1 ? { folder: '', name: path } : { folder: path.slice(0, idx), name: path.slice(idx + 1) }
}

export function ProgressBar({ progress, startedAt }: { progress: CompareProgress; startedAt?: string | null }) {
  const pct =
    progress.filesTotal > 0 ? Math.min(100, Math.round((progress.filesDone / progress.filesTotal) * 100)) : 0
  const current = progress.currentPath ? splitPath(progress.currentPath) : null

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-2 flex items-baseline justify-between text-sm">
        <span className="font-medium">
          {PHASE_LABEL[progress.phase]}
          {startedAt && (
            <span className="ml-2 font-normal text-neutral-400 dark:text-neutral-500">
              Started {new Date(startedAt).toLocaleString()}
            </span>
          )}
        </span>
        <span className="text-neutral-500">
          {progress.filesTotal > 0
            ? `${progress.filesDone.toLocaleString()} / ${progress.filesTotal.toLocaleString()} files`
            : 'counting…'}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
        <div
          className="h-full rounded-full bg-blue-500 transition-[width] duration-200"
          style={{ width: `${pct}%` }}
        />
      </div>
      {current && (
        <div className="mt-1.5 truncate font-mono text-xs text-neutral-500 dark:text-neutral-400">
          {current.folder && <span className="text-neutral-400 dark:text-neutral-500">{current.folder}/</span>}
          <span>{current.name}</span>
        </div>
      )}
    </div>
  )
}
