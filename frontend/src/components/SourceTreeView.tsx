import { useMemo, useRef, useState } from 'react'
import { Tree, type NodeRendererProps, type TreeApi } from 'react-arborist'
import type { CompareFile, TreeNode } from '../types'
import { buildSourceTree } from '../buildSourceTree'
import { CollapseToggle } from './CollapseToggle'

function FileRow({ node, style }: NodeRendererProps<TreeNode>) {
  const isFile = !!node.data.isFile

  return (
    <div
      style={style}
      onClick={() => !isFile && node.toggle()}
      className="flex cursor-pointer items-center gap-1.5 rounded px-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-800"
    >
      {!isFile && <span className="w-3 text-neutral-400 select-none">{node.isOpen ? '▾' : '▸'}</span>}
      {isFile && <span className="w-3" />}
      <span className={`truncate ${isFile ? 'text-neutral-600 dark:text-neutral-400' : 'font-medium'}`}>
        {node.data.name}
      </span>
      {isFile && node.data.category === 'source_only' && (
        <span className="ml-auto shrink-0 rounded-full bg-amber-100 px-1.5 py-0 text-[10px] whitespace-nowrap text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
          missing
        </span>
      )}
    </div>
  )
}

interface SourceTreeViewProps {
  files: CompareFile[]
  sourceRoots: string[]
}

export function SourceTreeView({ files, sourceRoots }: SourceTreeViewProps) {
  const [missingOnly, setMissingOnly] = useState(true)
  const [collapsed, setCollapsed] = useState(false)
  const treeRef = useRef<TreeApi<TreeNode> | undefined>(undefined)
  const data = useMemo(() => buildSourceTree(files, sourceRoots, missingOnly), [files, sourceRoots, missingOnly])

  return (
    <div className="rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-200 px-3 py-2 dark:border-neutral-800">
        <div className="flex items-center gap-1.5">
          <CollapseToggle collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} label="source tree" />
          <span className="text-xs font-medium tracking-wide text-neutral-500 uppercase">Source tree</span>
        </div>
        {!collapsed && (
          <div className="flex items-center gap-3">
            <div className="flex gap-1">
              <button
                onClick={() => treeRef.current?.openAll()}
                className="rounded border border-neutral-300 px-1.5 py-0.5 text-[11px] text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
              >
                Expand all
              </button>
              <button
                onClick={() => treeRef.current?.closeAll()}
                className="rounded border border-neutral-300 px-1.5 py-0.5 text-[11px] text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
              >
                Collapse all
              </button>
            </div>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs whitespace-nowrap text-neutral-600 dark:text-neutral-400">
              <input type="checkbox" checked={missingOnly} onChange={(e) => setMissingOnly(e.target.checked)} />
              Show only missing files
            </label>
          </div>
        )}
      </div>
      {!collapsed && (
        <div className="p-1">
          {data.length === 0 ? (
            <div className="p-4 text-center text-xs text-neutral-500">Nothing missing — source and target match.</div>
          ) : (
            <Tree ref={treeRef} data={data} openByDefault={missingOnly} width="100%" height={420} rowHeight={26} indent={16}>
              {FileRow}
            </Tree>
          )}
        </div>
      )}
    </div>
  )
}
