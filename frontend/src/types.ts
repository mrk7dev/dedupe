export type MountKind = 'internal' | 'external'

export interface TreeNode {
  id: string
  name: string
  children?: TreeNode[]
  kind?: MountKind // set on top-level mount nodes only
  isFile?: boolean
  category?: MatchCategory // set on file leaves within a results tree
  hasChildren?: boolean // set on folder-picker nodes; children loaded lazily on expand
}

export type ComparePhase = 'idle' | 'counting' | 'scanning' | 'hashing' | 'ready' | 'error' | 'cancelled'

export interface CompareProgress {
  phase: ComparePhase
  filesTotal: number
  filesDone: number
  currentPath: string | null
}

export type MatchCategory = 'matched' | 'source_only' | 'target_only'

export interface CompareFile {
  id: string
  dir: string
  path: string
  name: string
  sizeBytes: number
  category: MatchCategory
}

export interface CopyProgress {
  total: number
  done: number
}
