interface CollapseToggleProps {
  collapsed: boolean
  onToggle: () => void
  label?: string
}

export function CollapseToggle({ collapsed, onToggle, label }: CollapseToggleProps) {
  return (
    <button
      onClick={onToggle}
      aria-label={collapsed ? `Expand ${label ?? 'section'}` : `Collapse ${label ?? 'section'}`}
      aria-expanded={!collapsed}
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700 dark:hover:bg-neutral-800 dark:hover:text-neutral-200"
    >
      <span className={`inline-block text-xs transition-transform ${collapsed ? '-rotate-90' : ''}`}>▾</span>
    </button>
  )
}
