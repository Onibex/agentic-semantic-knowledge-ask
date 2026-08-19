/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Recycle } from 'lucide-react'

import type { DataProductStatus } from '@/api/types'

/**
 * A Data Product chip for the workspace home (UX_CHANGES audit §5.5 / design
 * spec fig. 2): coloured by medallion layer, with a lifecycle status dot and a
 * "reused" badge when the DP is shared across more than one Business Domain.
 *
 * Optional `devPublished` / `prodPublished` render compact env ticks so an admin
 * can see at a glance whether an entity is live in each environment — i.e. why a
 * data-product member may or may not be answerable when the chat targets that env
 * (queryable scope = data-product membership ∩ entities published to the env).
 * When neither prop is passed the chip keeps its original look (back-compat).
 */

const LAYER_CLS: Record<string, string> = {
  gold: 'bg-amber-50 border-amber-300 text-amber-800',
  silver: 'bg-emerald-50 border-emerald-300 text-emerald-800',
  bronze: 'bg-orange-50 border-orange-300 text-orange-800',
}

function dotClass(status?: DataProductStatus | null): string {
  if (status === 'Released') return 'bg-green-500'
  if (status === 'In Review') return 'bg-amber-500'
  return 'bg-gray-300' // not tracked yet
}

function EnvTick({ label, on, onCls }: { label: string; on: boolean; onCls: string }) {
  return (
    <span
      className={`rounded px-1 text-[9px] font-semibold uppercase leading-none ${
        on ? onCls : 'bg-black/5 text-gray-400 line-through opacity-60'
      }`}
      title={on ? `Published to ${label}` : `Not published to ${label} — not answerable when chat targets ${label}`}
    >
      {label}
    </span>
  )
}

export function DataProductChip({
  name,
  layer,
  status,
  reused = false,
  devPublished,
  prodPublished,
}: {
  name: string
  layer: string | null
  status?: DataProductStatus | null
  reused?: boolean
  devPublished?: boolean
  prodPublished?: boolean
}) {
  const cls = LAYER_CLS[(layer ?? '').toLowerCase()] ?? 'bg-gray-50 border-gray-200 text-gray-600'
  const showEnv = devPublished !== undefined || prodPublished !== undefined
  const envTitle = showEnv
    ? ` · dev:${devPublished ? '✓' : '✗'} prod:${prodPublished ? '✓' : '✗'}`
    : ''
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${cls}`}
      title={`${name}${status ? ` · ${status}` : ''}${envTitle}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${dotClass(status)}`} />
      <span className="font-mono truncate max-w-[180px]">{name}</span>
      {showEnv && (
        <span className="inline-flex items-center gap-0.5">
          <EnvTick label="dev" on={!!devPublished} onCls="bg-blue-100 text-blue-700" />
          <EnvTick label="prod" on={!!prodPublished} onCls="bg-green-100 text-green-700" />
        </span>
      )}
      {reused && (
        <span className="inline-flex items-center gap-0.5 rounded bg-black/5 px-1 text-[9px] font-medium opacity-70">
          <Recycle size={9} />
          reused
        </span>
      )}
    </span>
  )
}
