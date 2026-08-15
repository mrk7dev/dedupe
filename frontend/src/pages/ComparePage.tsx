import { useEffect, useRef, useState } from 'react'
import { FolderPickerModal } from '../components/FolderPickerModal'
import { FolderSelectButton } from '../components/FolderSelectButton'
import { ProgressBar } from '../components/ProgressBar'
import { ResultsTable } from '../components/ResultsTable'
import { SourceTreeView } from '../components/SourceTreeView'
import { getCompareResults, getCompareStatus, getCopyStatus, startCompare, startCopy } from '../api'
import type { CompareFile, CompareProgress, CopyProgress } from '../types'

const IDLE_PROGRESS: CompareProgress = { phase: 'idle', filesTotal: 0, filesDone: 0 }
const POLL_MS = 500

type PickerTarget = 'source' | 'target' | null

export function ComparePage() {
  const [sourceRoot, setSourceRoot] = useState<string | null>(null)
  const [targetRoot, setTargetRoot] = useState<string | null>(null)
  const [pickerTarget, setPickerTarget] = useState<PickerTarget>(null)
  const [runId, setRunId] = useState<number | null>(null)
  const [progress, setProgress] = useState<CompareProgress>(IDLE_PROGRESS)
  const [files, setFiles] = useState<CompareFile[] | null>(null)
  const [copyNotice, setCopyNotice] = useState<string | null>(null)
  const [copyProgress, setCopyProgress] = useState<CopyProgress | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Guards the poll loops below from touching state after unmount — there's
  // no interval to clear since each loop just awaits itself in sequence.
  // Reset on mount (not just set on cleanup) — StrictMode double-invokes
  // this effect once in dev, and without the reset the cleanup's `true`
  // from that synthetic unmount would permanently wedge every poll loop.
  const stoppedRef = useRef(false)
  useEffect(() => {
    stoppedRef.current = false
    return () => {
      stoppedRef.current = true
    }
  }, [])

  function errMsg(err: unknown): string {
    return err instanceof Error ? err.message : String(err)
  }

  async function startComparison() {
    if (!sourceRoot || !targetRoot) return
    setFiles(null)
    setCopyNotice(null)
    setCopyProgress(null)
    setError(null)
    setProgress({ phase: 'counting', filesTotal: 0, filesDone: 0 })

    let id: number
    try {
      id = await startCompare(sourceRoot, targetRoot)
    } catch (err) {
      setProgress(IDLE_PROGRESS)
      setError(errMsg(err))
      return
    }
    setRunId(id)

    while (!stoppedRef.current) {
      try {
        const status = await getCompareStatus(id)
        setProgress({ phase: status.phase, filesTotal: status.filesTotal, filesDone: status.filesDone })

        if (status.phase === 'ready') {
          const results = await getCompareResults(id)
          if (!stoppedRef.current) setFiles(results)
          return
        }
        if (status.phase === 'error') {
          setError(status.error ?? 'Comparison failed.')
          return
        }
      } catch (err) {
        if (stoppedRef.current) return
        setProgress((p) => ({ ...p, phase: 'error' }))
        setError(errMsg(err))
        return
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_MS))
    }
  }

  async function handleCopySelected(selected: CompareFile[]) {
    if (selected.length === 0 || runId === null) return
    setCopyNotice(null)
    setError(null)

    try {
      await startCopy(
        runId,
        selected.map((f) => Number(f.id)),
      )
    } catch (err) {
      setError(errMsg(err))
      return
    }
    setCopyProgress({ total: selected.length, done: 0 })

    while (!stoppedRef.current) {
      try {
        const status = await getCopyStatus(runId)
        setCopyProgress({ total: status.total, done: status.done })

        if (status.phase === 'done') {
          const results = await getCompareResults(runId)
          if (!stoppedRef.current) {
            setFiles(results)
            setCopyNotice(`Copied ${status.done} file${status.done === 1 ? '' : 's'} to target.`)
            window.setTimeout(() => {
              if (!stoppedRef.current) setCopyProgress(null)
            }, 500)
          }
          return
        }
        if (status.phase === 'error') {
          setError(status.error ?? 'Copy failed.')
          setCopyProgress(null)
          return
        }
      } catch (err) {
        if (stoppedRef.current) return
        setError(errMsg(err))
        setCopyProgress(null)
        return
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_MS))
    }
  }

  const isRunning = progress.phase !== 'idle' && progress.phase !== 'ready' && progress.phase !== 'error'

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">Compare volumes</h1>
        <p className="text-sm text-neutral-500">
          Pick a source and target folder, then find what's missing from target by content — not by path.
        </p>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row">
        <FolderSelectButton label="Source" path={sourceRoot} onClick={() => setPickerTarget('source')} />
        <FolderSelectButton label="Target" path={targetRoot} onClick={() => setPickerTarget('target')} />
      </div>

      {pickerTarget && (
        <FolderPickerModal
          title={pickerTarget === 'source' ? 'Select source folder' : 'Select target folder'}
          initialPath={pickerTarget === 'source' ? sourceRoot : targetRoot}
          onCancel={() => setPickerTarget(null)}
          onConfirm={(path) => {
            if (pickerTarget === 'source') setSourceRoot(path)
            else setTargetRoot(path)
            setPickerTarget(null)
          }}
        />
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={startComparison}
          disabled={!sourceRoot || !targetRoot || isRunning}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-neutral-300 dark:bg-neutral-100 dark:text-neutral-900 dark:disabled:bg-neutral-700 dark:disabled:text-neutral-400"
        >
          {isRunning ? 'Comparing…' : 'Start comparison'}
        </button>
        {!sourceRoot || !targetRoot ? (
          <span className="text-xs text-neutral-500">Select a source and target folder to enable this.</span>
        ) : null}
      </div>

      {progress.phase !== 'idle' && <ProgressBar progress={progress} />}

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-900/30 dark:text-red-300">
          {error}
        </div>
      )}

      {copyNotice && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-300">
          {copyNotice}
        </div>
      )}

      {files && sourceRoot && (
        <div className="flex flex-col gap-4 lg:flex-row">
          <div className="lg:w-80 lg:shrink-0">
            <SourceTreeView files={files} sourceRoot={sourceRoot} />
          </div>
          <div className="min-w-0 flex-1">
            <ResultsTable files={files} onCopySelected={handleCopySelected} copyProgress={copyProgress} />
          </div>
        </div>
      )}
    </div>
  )
}
