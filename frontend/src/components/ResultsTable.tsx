import { useMemo, useRef, useState } from 'react'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  type RowSelectionState,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { CompareFile, CopyProgress } from '../types'
import { formatBytes } from '../format'
import { CollapseToggle } from './CollapseToggle'

type FilterMode = 'missing' | 'all'

const CATEGORY_LABEL: Record<CompareFile['category'], string> = {
  matched: 'On both',
  source_only: 'Missing from target',
  target_only: 'Only on target',
}

const CATEGORY_BADGE: Record<CompareFile['category'], string> = {
  matched: 'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400',
  source_only: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  target_only: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
}

const columnHelper = createColumnHelper<CompareFile>()

interface ResultsTableProps {
  files: CompareFile[]
  onCopySelected: (files: CompareFile[]) => void
  copyProgress: CopyProgress | null
}

export function ResultsTable({ files, onCopySelected, copyProgress }: ResultsTableProps) {
  const [filterMode, setFilterMode] = useState<FilterMode>('missing')
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [collapsed, setCollapsed] = useState(false)
  const isCopying = copyProgress !== null && copyProgress.done < copyProgress.total

  const counts = useMemo(
    () => ({
      matched: files.filter((f) => f.category === 'matched').length,
      source_only: files.filter((f) => f.category === 'source_only').length,
      target_only: files.filter((f) => f.category === 'target_only').length,
    }),
    [files],
  )

  const visibleFiles = useMemo(
    () => (filterMode === 'missing' ? files.filter((f) => f.category === 'source_only') : files),
    [files, filterMode],
  )

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: 'select',
        header: ({ table }) => (
          <input
            type="checkbox"
            checked={table.getIsAllRowsSelected()}
            ref={(el) => {
              if (el) el.indeterminate = table.getIsSomeRowsSelected() && !table.getIsAllRowsSelected()
            }}
            onChange={table.getToggleAllRowsSelectedHandler()}
            disabled={filterMode === 'all' || isCopying}
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            checked={row.getIsSelected()}
            onChange={row.getToggleSelectedHandler()}
            disabled={row.original.category !== 'source_only' || isCopying}
          />
        ),
        size: 32,
        enableResizing: false,
      }),
      columnHelper.accessor('dir', {
        header: 'Path',
        cell: (info) => <span className="truncate font-mono text-xs text-neutral-500">{info.getValue()}</span>,
        size: 320,
        minSize: 120,
        maxSize: 800,
      }),
      columnHelper.accessor('name', {
        header: 'Name',
        cell: (info) => <span className="truncate font-mono text-xs">{info.getValue()}</span>,
        size: 200,
        minSize: 80,
        maxSize: 500,
      }),
      columnHelper.accessor('sizeBytes', {
        header: 'Size',
        cell: (info) => <span className="text-neutral-500">{formatBytes(info.getValue())}</span>,
        size: 90,
        minSize: 60,
        maxSize: 200,
      }),
      columnHelper.accessor('category', {
        header: 'Status',
        cell: (info) => (
          <span className={`rounded-full px-2 py-0.5 text-xs whitespace-nowrap ${CATEGORY_BADGE[info.getValue()]}`}>
            {CATEGORY_LABEL[info.getValue()]}
          </span>
        ),
        size: 160,
        minSize: 100,
        maxSize: 300,
      }),
    ],
    [filterMode, isCopying],
  )

  const table = useReactTable({
    data: visibleFiles,
    columns,
    state: { rowSelection },
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.id,
    enableRowSelection: (row) => row.original.category === 'source_only',
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
  })

  const rows = table.getRowModel().rows
  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 34,
    overscan: 12,
  })

  const selectedFiles = useMemo(() => rows.filter((r) => r.getIsSelected()).map((r) => r.original), [rows, rowSelection])
  const selectedCount = selectedFiles.length
  const selectedBytes = useMemo(() => selectedFiles.reduce((sum, f) => sum + f.sizeBytes, 0), [selectedFiles])
  const totalWidth = table.getTotalSize()
  const copyPct = copyProgress && copyProgress.total > 0 ? Math.round((copyProgress.done / copyProgress.total) * 100) : 0

  return (
    <div className="rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-neutral-200 p-3 dark:border-neutral-800">
        <div className="flex items-center gap-2">
          <CollapseToggle collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} label="results" />
          <div className="flex gap-1.5">
            <button
              onClick={() => setFilterMode('missing')}
              disabled={isCopying}
              className={`rounded-full px-3 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-60 ${
                filterMode === 'missing'
                  ? 'bg-amber-500 text-white'
                  : 'border border-neutral-300 text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800'
              }`}
            >
              Missing from target ({counts.source_only})
            </button>
            <button
              onClick={() => setFilterMode('all')}
              disabled={isCopying}
              className={`rounded-full px-3 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-60 ${
                filterMode === 'all'
                  ? 'bg-neutral-800 text-white dark:bg-neutral-200 dark:text-neutral-900'
                  : 'border border-neutral-300 text-neutral-600 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800'
              }`}
            >
              All files ({files.length})
            </button>
          </div>
        </div>

        {isCopying ? (
          <div className="flex min-w-0 flex-1 items-center gap-2 pl-4 sm:max-w-xs">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
              <div
                className="h-full rounded-full bg-blue-500 transition-[width] duration-150"
                style={{ width: `${copyPct}%` }}
              />
            </div>
            <span className="shrink-0 text-xs whitespace-nowrap text-neutral-500">
              Copying {copyProgress!.done} / {copyProgress!.total}
            </span>
          </div>
        ) : (
          <button
            disabled={selectedCount === 0}
            onClick={() => onCopySelected(selectedFiles)}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-neutral-300 dark:disabled:bg-neutral-700"
          >
            {selectedCount > 0
              ? `Copy ${selectedCount} selected (${formatBytes(selectedBytes)}) to target`
              : 'Copy selected to target'}
          </button>
        )}
      </div>

      {!collapsed && (
        <>
          <div className="flex gap-2 border-b border-neutral-100 px-3 py-1.5 text-xs text-neutral-500 dark:border-neutral-800">
            <span>{counts.matched} on both</span>
            <span>·</span>
            <span>{counts.source_only} missing from target</span>
            <span>·</span>
            <span>{counts.target_only} only on target</span>
          </div>

          <div ref={scrollRef} className="h-96 overflow-auto">
            <div style={{ width: totalWidth, minWidth: '100%' }}>
              <div className="sticky top-0 z-10 flex bg-neutral-50 text-xs font-medium text-neutral-500 dark:bg-neutral-900 dark:text-neutral-400">
                {table.getFlatHeaders().map((header) => (
                  <div
                    key={header.id}
                    style={{ width: header.getSize() }}
                    className="relative border-b border-neutral-200 px-2 py-2 dark:border-neutral-800"
                  >
                    <span className="truncate">{flexRender(header.column.columnDef.header, header.getContext())}</span>
                    {header.column.getCanResize() && (
                      <div
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        className={`absolute top-0 right-0 h-full w-1.5 cursor-col-resize touch-none select-none ${
                          header.column.getIsResizing()
                            ? 'bg-blue-500'
                            : 'hover:bg-neutral-300 dark:hover:bg-neutral-600'
                        }`}
                      />
                    )}
                  </div>
                ))}
              </div>
              <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
                {virtualizer.getVirtualItems().map((virtualRow) => {
                  const row = rows[virtualRow.index]
                  return (
                    <div
                      key={row.id}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: virtualRow.size,
                        transform: `translateY(${virtualRow.start}px)`,
                      }}
                      className="flex items-center border-b border-neutral-100 text-sm dark:border-neutral-800"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <div key={cell.id} style={{ width: cell.column.getSize() }} className="truncate px-2">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </div>
                      ))}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
