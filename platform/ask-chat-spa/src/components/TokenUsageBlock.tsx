/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight, Activity } from 'lucide-react'
import type { TokensBreakdown } from '@/api/orchestrator'

// Per-turn token accounting, rendered from `QueryResponse.tokens_breakdown`
// (the orchestrator's per-request TokenTracker summary).
//
// Tokens only — cost is deliberately absent. The same model is priced
// differently per channel (Bedrock / Azure / SAP AI Core / direct), so a local
// estimate would misrepresent the real bill; the authoritative cost lives in
// each provider's billing console.

interface TokenUsageBlockProps {
  breakdown: TokensBreakdown
}

const num = (n: number | undefined) => (n ?? 0).toLocaleString()

/** ISO-8601 UTC → HH:MM:SS in the viewer's locale. Falls back to the raw value. */
function shortTime(iso: string | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleTimeString()
}

// ── Tables ────────────────────────────────────────────────────────────────────

function ByPhaseTable({ breakdown }: TokenUsageBlockProps) {
  const entries = Object.entries(breakdown.by_phase ?? {})
  if (entries.length === 0) return null

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full text-xs">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            {['Phase', 'Calls', 'Input', 'Output', 'Total'].map((h, i) => (
              <th
                key={h}
                className={`px-3 py-2 font-semibold text-gray-600 whitespace-nowrap ${
                  i === 0 ? 'text-left' : 'text-right'
                }`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map(([phase, v], i) => (
            <tr
              key={phase}
              className={`border-b border-gray-100 ${i % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}`}
            >
              <td className="px-3 py-1.5 text-gray-700 whitespace-nowrap">{phase}</td>
              <td className="px-3 py-1.5 text-right text-gray-700 font-mono tabular-nums">
                {num(v?.calls)}
              </td>
              <td className="px-3 py-1.5 text-right text-gray-700 font-mono tabular-nums">
                {num(v?.input_tokens)}
              </td>
              <td className="px-3 py-1.5 text-right text-gray-700 font-mono tabular-nums">
                {num(v?.output_tokens)}
              </td>
              <td className="px-3 py-1.5 text-right text-gray-800 font-mono tabular-nums font-semibold">
                {num(v?.total_tokens)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PerCallTable({ breakdown }: TokenUsageBlockProps) {
  const records = breakdown.records ?? []
  if (records.length === 0) return null

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full text-xs">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            {['Phase', 'Model', 'Input', 'Output', 'Total', 'Time'].map((h, i) => (
              <th
                key={h}
                className={`px-3 py-2 font-semibold text-gray-600 whitespace-nowrap ${
                  i >= 2 && i <= 4 ? 'text-right' : 'text-left'
                }`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((r, i) => (
            <tr
              key={`${r.phase}-${r.timestamp_utc}-${i}`}
              className={`border-b border-gray-100 ${i % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}`}
            >
              <td className="px-3 py-1.5 text-gray-700 whitespace-nowrap">{r.phase}</td>
              <td className="px-3 py-1.5 text-gray-500 whitespace-nowrap font-mono text-[11px]">
                {r.model}
              </td>
              <td className="px-3 py-1.5 text-right text-gray-700 font-mono tabular-nums">
                {num(r.input_tokens)}
              </td>
              <td className="px-3 py-1.5 text-right text-gray-700 font-mono tabular-nums">
                {num(r.output_tokens)}
              </td>
              <td className="px-3 py-1.5 text-right text-gray-800 font-mono tabular-nums font-semibold">
                {num(r.total_tokens)}
              </td>
              <td className="px-3 py-1.5 text-gray-400 whitespace-nowrap tabular-nums">
                {shortTime(r.timestamp_utc)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main block ────────────────────────────────────────────────────────────────

/**
 * Renders a chip + (when expanded) a full-width detail panel.
 *
 * Returns a Fragment on purpose: the parent badge row is `flex flex-wrap`, so
 * the `basis-full` panel wraps onto its own line at full width while the chip
 * stays inline next to the mode badge.
 */
export function TokenUsageBlock({ breakdown }: TokenUsageBlockProps) {
  const [open, setOpen] = useState(false)

  if (!breakdown || (breakdown.total_calls ?? 0) === 0) return null

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        title="LLM calls and tokens consumed by this answer"
        className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium text-gray-400 bg-gray-100 hover:bg-gray-200 hover:text-gray-600 transition-colors cursor-pointer"
      >
        <Activity className="h-3 w-3" />
        {breakdown.total_calls} LLM {breakdown.total_calls === 1 ? 'call' : 'calls'} ·{' '}
        {num(breakdown.total_tokens)} tok
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
      </button>

      {open && (
        <div className="basis-full w-full mt-1 space-y-2">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-500">
            <span>
              Input <span className="font-mono tabular-nums text-gray-700">{num(breakdown.input_tokens)}</span>
            </span>
            <span>
              Output <span className="font-mono tabular-nums text-gray-700">{num(breakdown.output_tokens)}</span>
            </span>
            <span>
              Total <span className="font-mono tabular-nums text-gray-800 font-semibold">{num(breakdown.total_tokens)}</span>
            </span>
          </div>

          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
            By phase
          </p>
          <ByPhaseTable breakdown={breakdown} />

          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
            Per-call detail
          </p>
          <PerCallTable breakdown={breakdown} />
        </div>
      )}
    </>
  )
}
