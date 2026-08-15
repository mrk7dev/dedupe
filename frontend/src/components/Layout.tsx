import type { ReactNode } from 'react'

export type Page = 'compare' | 'duplicates'

interface LayoutProps {
  page: Page
  onNavigate: (page: Page) => void
  children: ReactNode
}

export function Layout({ page, onNavigate, children }: LayoutProps) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3">
          <span className="font-semibold">dedupe</span>
          <nav className="flex gap-4 text-sm">
            <button
              onClick={() => onNavigate('duplicates')}
              className={page === 'duplicates' ? 'font-medium text-blue-600 dark:text-blue-400' : 'text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200'}
            >
              Duplicates
            </button>
            <button
              onClick={() => onNavigate('compare')}
              className={page === 'compare' ? 'font-medium text-blue-600 dark:text-blue-400' : 'text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200'}
            >
              Compare
            </button>
          </nav>
          <span className="ml-auto rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
            mockup — mock data
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-6">{children}</main>
    </div>
  )
}
