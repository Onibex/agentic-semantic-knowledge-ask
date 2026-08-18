/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Domain Canvas "Knowledge" rail tab (design-spec §03). Lists the Data Products
 * NOT yet in this domain so the curator can add them — by dragging onto the
 * canvas (sets the ASK_ENTITY_DND payload) or clicking "+". Both routes call
 * `onAdd(entityId)`, which the canvas turns into a BD-membership update.
 *
 * DPs are silver/gold entities; bronzes are never standalone DPs (they nest via
 * composed_of), so they're filtered out of the pickable list.
 */

import { useEffect, useMemo, useState } from 'react'
import { Loader2, Plus, Search } from 'lucide-react'

import { listYamls } from '../../api/client'
import type { BusinessDomain, YAMLNodeSummary } from '../../api/types'
import { ASK_ENTITY_DND } from '../graph/YAMLGraph'
import { useTranslation } from '../../hooks/useTranslation'

interface Props {
  domain: BusinessDomain
  onAdd: (entityId: string) => void
}

export function DomainKnowledgePanel({ domain, onAdd }: Props) {
  const { t } = useTranslation()
  const [items, setItems] = useState<YAMLNodeSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')

  useEffect(() => {
    // `loading` already defaults to true; the catalog is fetched once on mount.
    let cancelled = false
    listYamls()
      .then((all) => {
        if (!cancelled) setItems(all)
      })
      .catch(() => {
        if (!cancelled) setItems([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const inDomain = useMemo(
    () => new Set(domain.data_product_ids ?? []),
    [domain.data_product_ids],
  )

  const available = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return items
      .filter((y) => y.layer === 'silver' || y.layer === 'gold')
      .filter((y) => !inDomain.has(y.id))
      .filter(
        (y) =>
          !needle ||
          y.name.toLowerCase().includes(needle) ||
          y.id.toLowerCase().includes(needle),
      )
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [items, inDomain, q])

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="shrink-0 p-3 border-b border-gray-200">
        <p className="text-[11px] text-gray-500 mb-2 leading-snug">
          {t('dkp_drag_hint')}
        </p>
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('dkp_filter_ph')}
            className="w-full text-xs border border-gray-300 rounded-md pl-7 pr-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-gray-400">
            <Loader2 size={14} className="animate-spin" />
          </div>
        ) : available.length === 0 ? (
          <p className="text-center text-xs text-gray-400 py-8 px-3">
            {items.length === 0
              ? t('dkp_no_catalog')
              : t('dkp_all_in_domain')}
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {available.map((y) => (
              <li
                key={y.id}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData(ASK_ENTITY_DND, y.id)
                  e.dataTransfer.effectAllowed = 'copy'
                }}
                className="group flex items-center gap-2 rounded-md border border-gray-200 bg-white px-2 py-1.5 cursor-grab active:cursor-grabbing hover:border-blue-300 hover:bg-blue-50/40"
                title={y.id}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-medium text-gray-800 truncate">{y.name}</span>
                  <span className="block text-[10px] text-gray-400">
                    {y.layer}
                    {y.module ? ` · ${y.module}` : ''}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => onAdd(y.id)}
                  className="shrink-0 inline-flex h-5 w-5 items-center justify-center rounded border border-blue-300 text-blue-700 hover:bg-blue-100"
                  title="Add to this domain"
                  aria-label={`Add ${y.name} to this domain`}
                >
                  <Plus size={12} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
