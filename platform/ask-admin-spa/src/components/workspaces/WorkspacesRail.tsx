import { useMemo, useState } from 'react'
import { LayoutGrid, Plus, Search } from 'lucide-react'

import type { Workspace } from '@/api/types'
import { useTranslation } from '@/hooks/useTranslation'

/**
 * Left rail of the workspace home (design spec fig. 2): the list of workspaces
 * with their Business-Domain count, an active highlight, a filter, and a
 * "+ New workspace" action. Selecting one navigates to /workspaces/:slug.
 */
interface Props {
  workspaces: Workspace[]
  counts: Record<string, number>
  activeSlug?: string
  loading?: boolean
  onSelect: (ws: Workspace) => void
  onNew: () => void
}

export function WorkspacesRail({ workspaces, counts, activeSlug, loading, onSelect, onNew }: Props) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState('')
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return workspaces
    return workspaces.filter(
      (w) => w.name.toLowerCase().includes(q) || w.slug.toLowerCase().includes(q),
    )
  }, [workspaces, filter])

  return (
    <aside className="w-56 shrink-0 border-r border-gray-200 bg-gray-50 flex flex-col h-full overflow-hidden">
      <div className="p-3 border-b border-gray-200 shrink-0">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
          {t('ws_rail_title')}
        </div>
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('ws_rail_filter_ph')}
            className="w-full text-xs border border-gray-300 rounded-md pl-7 pr-2 py-1.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        {loading && workspaces.length === 0 ? (
          <div className="px-2 py-6 text-center text-xs text-gray-400">{t('common_loading')}</div>
        ) : filtered.length === 0 ? (
          <div className="px-2 py-6 text-center text-xs text-gray-400">
            {workspaces.length === 0 ? t('ws_rail_empty') : t('ws_rail_no_matches')}
          </div>
        ) : (
          filtered.map((ws) => {
            const active = ws.slug === activeSlug
            return (
              <button
                key={ws.id}
                onClick={() => onSelect(ws)}
                className={`w-full text-left flex items-center gap-2 px-2.5 py-2 rounded-md transition-colors ${
                  active ? 'bg-blue-50 text-blue-700' : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                <LayoutGrid size={14} className="shrink-0 opacity-70" />
                <span className="truncate text-[13px] font-medium flex-1">{ws.name}</span>
                <span
                  className={`text-[11px] tabular-nums ${active ? 'text-blue-500' : 'text-gray-400'}`}
                >
                  {counts[ws.id] ?? '·'}
                </span>
              </button>
            )
          })
        )}
      </div>

      <div className="p-2 border-t border-gray-200 shrink-0">
        <button
          onClick={onNew}
          className="w-full inline-flex items-center justify-center gap-1.5 rounded-md border border-dashed border-gray-300 px-2 py-2 text-xs text-gray-600 hover:bg-white hover:border-gray-400 transition-colors"
        >
          <Plus size={13} />
          {t('ws_rail_new_btn')}
        </button>
      </div>
    </aside>
  )
}
