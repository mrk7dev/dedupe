import type { CompareFile, CompareProgress } from './types'

export interface BrowseEntry {
  path: string
  name: string
  kind: 'internal' | 'external' | null
  hasChildren: boolean
}

interface BrowseResponse {
  path: string | null
  entries: BrowseEntry[]
}

interface StartCompareResponse {
  run_id: number
}

interface CompareStatusResponse {
  phase: CompareProgress['phase']
  filesTotal: number
  filesDone: number
  error: string | null
  sourceRoots: string[]
  targetRoots: string[]
  startedAt: string
}

interface CompareResultsResponse {
  files: CompareFile[]
}

export interface VersionInfo {
  version: string
  commit: string
  dirty: boolean
  builtAt: string | null
}

export type CopyPhase = 'running' | 'done' | 'error' | null

export interface CopyStatusResponse {
  phase: CopyPhase
  total: number
  done: number
  error: string | null
}

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
  return typeof detail === 'string' ? detail : `${res.status} ${res.statusText}`
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(await errorMessage(res))
  return (await res.json()) as T
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  return (await res.json()) as T
}

// GET /api/version — build info of whatever's currently deployed.
export function getVersion(): Promise<VersionInfo> {
  return getJSON<VersionInfo>('/api/version')
}

// GET /api/browse (no path) — the configured top-level mounts.
export function browseRoots(): Promise<BrowseEntry[]> {
  return getJSON<BrowseResponse>('/api/browse').then((r) => r.entries)
}

// GET /api/browse?path=... — immediate subdirectories of `path`.
export function browseChildren(path: string): Promise<BrowseEntry[]> {
  return getJSON<BrowseResponse>(`/api/browse?path=${encodeURIComponent(path)}`).then((r) => r.entries)
}

// POST /compare/start — kicks off a comparison run, returns its id.
export function startCompare(sourceRoots: string[], targetRoots: string[], ignoreCache = false): Promise<number> {
  return postJSON<StartCompareResponse>('/compare/start', {
    source_roots: sourceRoots,
    target_roots: targetRoots,
    ignore_cache: ignoreCache,
  }).then((r) => r.run_id)
}

// GET /compare/{id}/status — poll while a comparison is running.
export function getCompareStatus(runId: number): Promise<CompareStatusResponse> {
  return getJSON<CompareStatusResponse>(`/compare/${runId}/status`)
}

// GET /compare/{id}/results — call once status.phase === 'ready'.
export function getCompareResults(runId: number): Promise<CompareFile[]> {
  return getJSON<CompareResultsResponse>(`/compare/${runId}/results`).then((r) => r.files)
}

// POST /compare/{id}/copy — copy the given compare_file ids (source_only only) to target.
export function startCopy(runId: number, fileIds: number[]): Promise<void> {
  return postJSON<{ status: string; count: number }>(`/compare/${runId}/copy`, { file_ids: fileIds }).then(
    () => undefined,
  )
}

// GET /compare/{id}/copy/status — poll while a copy is running.
export function getCopyStatus(runId: number): Promise<CopyStatusResponse> {
  return getJSON<CopyStatusResponse>(`/compare/${runId}/copy/status`)
}

// POST /compare/{id}/stop — request cancellation of a running comparison.
export function stopCompare(runId: number): Promise<void> {
  return postJSON<{ status: string }>(`/compare/${runId}/stop`, {}).then(() => undefined)
}
