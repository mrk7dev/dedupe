import { useCallback, useEffect, useState } from 'react'
import { Tree, type NodeRendererProps } from 'react-arborist'
import type { TreeNode } from '../types'
import { browseChildren, browseRoots, type BrowseEntry } from '../api'

function toNode(entry: BrowseEntry): TreeNode {
  return {
    id: entry.path,
    name: entry.name,
    kind: entry.kind ?? undefined,
    hasChildren: entry.hasChildren,
    children: [], // always an array so react-arborist treats every folder as expandable, not a leaf
  }
}

// Replaces the (still-empty) `children` of the node with id `targetId`, anywhere in the tree.
function withChildrenLoaded(nodes: TreeNode[], targetId: string, children: TreeNode[]): TreeNode[] {
  return nodes.map((n) => {
    if (n.id === targetId) return { ...n, children }
    if (n.children && n.children.length > 0) return { ...n, children: withChildrenLoaded(n.children, targetId, children) }
    return n
  })
}

interface FolderPickerModalProps {
  title: string
  initialPath: string | null
  onCancel: () => void
  onConfirm: (path: string) => void
}

export function FolderPickerModal({ title, initialPath, onCancel, onConfirm }: FolderPickerModalProps) {
  const [picked, setPicked] = useState<string | null>(initialPath)
  const [roots, setRoots] = useState<TreeNode[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadedIds, setLoadedIds] = useState<Set<string>>(new Set())
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    browseRoots()
      .then((entries) => {
        if (!cancelled) setRoots(entries.map(toNode))
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
    return () => {
      cancelled = true
    }
  }, [])

  const loadChildren = useCallback(
    (node: TreeNode) => {
      if (!node.hasChildren || loadedIds.has(node.id) || loadingIds.has(node.id)) return
      setLoadingIds((prev) => new Set(prev).add(node.id))
      browseChildren(node.id)
        .then((entries) => {
          setRoots((prev) => (prev ? withChildrenLoaded(prev, node.id, entries.map(toNode)) : prev))
          setLoadedIds((prev) => new Set(prev).add(node.id))
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)))
        .finally(() => {
          setLoadingIds((prev) => {
            const next = new Set(prev)
            next.delete(node.id)
            return next
          })
        })
    },
    [loadedIds, loadingIds],
  )

  function Row({ node, style }: NodeRendererProps<TreeNode>) {
    const isMount = node.level === 0
    const hasChildren = !!node.data.hasChildren
    const isLoading = loadingIds.has(node.data.id)

    return (
      <div
        style={style}
        onClick={() => {
          if (hasChildren) {
            if (!node.isOpen) loadChildren(node.data)
            node.toggle()
          }
          node.select()
        }}
        className={`flex cursor-pointer items-center gap-1.5 rounded px-1.5 text-sm ${
          node.isSelected
            ? 'bg-blue-100 text-blue-900 dark:bg-blue-900/40 dark:text-blue-200'
            : 'hover:bg-neutral-100 dark:hover:bg-neutral-800'
        }`}
      >
        {hasChildren ? (
          <span className="w-3 text-neutral-400 select-none">{node.isOpen ? '▾' : '▸'}</span>
        ) : (
          <span className="w-3" />
        )}
        <span className={`truncate ${isMount ? 'font-medium' : ''}`}>{node.data.name}</span>
        {isLoading && <span className="text-[10px] text-neutral-400">loading…</span>}
        {isMount && (
          <span className="ml-auto shrink-0 rounded-full bg-neutral-200 px-1.5 py-0 text-[10px] text-neutral-600 dark:bg-neutral-700 dark:text-neutral-300">
            {node.data.kind === 'external' ? 'external drive' : 'volume'}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onCancel}>
      <div
        className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg border border-neutral-200 bg-white shadow-xl dark:border-neutral-800 dark:bg-neutral-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
          <div className="text-sm font-semibold">{title}</div>
          <div className="mt-0.5 text-xs text-neutral-500">
            Browse the DiskStation's volumes and mounted drives, then pick a folder.
          </div>
        </div>

        <div className="flex-1 overflow-auto p-2">
          {error && (
            <div className="m-1 rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700 dark:border-red-900 dark:bg-red-900/30 dark:text-red-300">
              {error}
            </div>
          )}
          {roots === null && !error ? (
            <div className="p-4 text-center text-xs text-neutral-500">Loading…</div>
          ) : (
            <Tree
              data={roots ?? []}
              openByDefault={false}
              width="100%"
              height={360}
              rowHeight={26}
              indent={16}
              selection={picked ?? undefined}
              onSelect={(nodes) => {
                const node = nodes[0]
                if (node) setPicked(node.data.id)
              }}
            >
              {Row}
            </Tree>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-neutral-200 px-4 py-3 dark:border-neutral-800">
          <span className="min-w-0 truncate font-mono text-xs text-neutral-500">
            {picked ?? 'nothing selected'}
          </span>
          <div className="flex shrink-0 gap-2">
            <button
              onClick={onCancel}
              className="rounded-md border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-200 dark:hover:bg-neutral-800"
            >
              Cancel
            </button>
            <button
              disabled={!picked}
              onClick={() => picked && onConfirm(picked)}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-neutral-300 dark:disabled:bg-neutral-700"
            >
              Select folder
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
