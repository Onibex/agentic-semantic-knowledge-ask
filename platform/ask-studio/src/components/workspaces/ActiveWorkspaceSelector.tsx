/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { LayoutGrid, Loader2 } from 'lucide-react'
import { useEffect } from 'react'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { useTranslation } from '@/hooks/useTranslation'

/**
 * Compact workspace picker mounted in the sidebar, just below the brand.
 *
 * Drives the global active-workspace context consumed by Graph / Knowledge /
 * Merge / History. Persists to localStorage via the store so a refresh
 * restores the same scope.
 */
export function ActiveWorkspaceSelector() {
  const { t } = useTranslation()
  const { available, activeWorkspaceId, loading, loadWorkspaces, setActive } = useWorkspaceStore()

  useEffect(() => {
    void loadWorkspaces()
  }, [loadWorkspaces])

  // Initial selection when nothing is persisted AND there's exactly one
  // workspace — saves the admin a click. Multiple workspaces stay
  // unselected so the admin makes an explicit choice.
  useEffect(() => {
    if (!loading && !activeWorkspaceId && available.length === 1) {
      setActive(available[0].id)
    }
  }, [loading, activeWorkspaceId, available, setActive])

  if (loading && available.length === 0) {
    return (
      <div className="px-3 py-2 text-[11px] text-gray-400 flex items-center gap-1.5">
        <Loader2 size={11} className="animate-spin" />
        {t('aws_loading')}
      </div>
    )
  }

  if (available.length === 0) {
    return (
      <div className="mx-3 mt-2 px-2 py-2 rounded border border-dashed border-amber-300 bg-amber-50 text-[11px] text-amber-900">
        {t('aws_no_ws')}{' '}
        <a href="/workspaces" className="font-medium underline">
          {t('aws_create_one')}
        </a>
        .
      </div>
    )
  }

  return (
    <div className="px-3 pt-2 pb-3 space-y-1">
      <label
        htmlFor="active-workspace-select"
        className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400"
      >
        <LayoutGrid size={10} /> {t('aws_label')}
      </label>
      <Select
        value={activeWorkspaceId ?? ''}
        onValueChange={(v) => setActive(v || null)}
      >
        <SelectTrigger
          id="active-workspace-select"
          className="h-8 text-xs"
          aria-label={t('aws_label')}
        >
          <SelectValue placeholder={t('aws_placeholder')} />
        </SelectTrigger>
        <SelectContent>
          {available.map((w) => (
            <SelectItem key={w.id} value={w.id}>
              <div className="flex flex-col">
                <span className="text-xs font-medium">{w.name || w.slug}</span>
                <span className="text-[10px] text-gray-500">{w.slug}</span>
              </div>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
