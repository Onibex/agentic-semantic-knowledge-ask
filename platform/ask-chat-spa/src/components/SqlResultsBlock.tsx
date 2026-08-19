/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight, Copy, Check, Table2, BarChart2 } from 'lucide-react'
import { AutoChart } from './AutoChart'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/hooks/useTranslation'

type Row = Record<string, unknown>

interface SqlResultsBlockProps {
  rows: Row[]
  sql?: string | null
  answerText?: string
}

// ── Copy button ────────────────────────────────────────────────────────────────

function CopyButton({ text, labelKey = 'results_copy' }: { text: string; labelKey?: 'results_copy' | 'results_copy_answer' | 'results_copy_sql' }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? t('results_copied') : t(labelKey)}
    </button>
  )
}

// ── Data table ─────────────────────────────────────────────────────────────────

function DataTable({ rows }: { rows: Row[] }) {
  if (rows.length === 0) return null
  const columns = Object.keys(rows[0])
  const preview = rows.slice(0, 100)

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full text-xs">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            {columns.map((col) => (
              <th
                key={col}
                className="px-3 py-2 text-left font-semibold text-gray-600 whitespace-nowrap"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.map((row, i) => (
            <tr
              key={i}
              className={cn('border-b border-gray-100', i % 2 === 0 ? 'bg-white' : 'bg-gray-50/50')}
            >
              {columns.map((col) => (
                <td
                  key={col}
                  className="px-3 py-1.5 text-gray-700 whitespace-nowrap font-mono tabular-nums"
                >
                  {String(row[col] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 100 && (
        <ShowingRowsNote shown={100} total={rows.length} />
      )}
    </div>
  )
}

// ── Showing N of M rows note ──────────────────────────────────────────────────

function ShowingRowsNote({ shown, total }: { shown: number; total: number }) {
  const { t } = useTranslation()
  const label = t('results_showing_rows')
    .replace('{shown}', String(shown))
    .replace('{total}', String(total))
  return (
    <p className="px-3 py-1.5 text-[10px] text-gray-400 bg-gray-50 border-t border-gray-100">
      {label}
    </p>
  )
}

// ── SQL collapsible ────────────────────────────────────────────────────────────

function SqlBlock({ sql }: { sql: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-lg border border-gray-200 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
          {t('results_sql_query')}
        </span>
        <div className="flex items-center gap-1">
          {open && (
            <span onClick={(e) => e.stopPropagation()}>
              <CopyButton text={sql} labelKey="results_copy_sql" />
            </span>
          )}
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
          )}
        </div>
      </button>
      {open && (
        <pre className="overflow-x-auto px-4 py-3 text-[11px] leading-relaxed text-blue-900 bg-blue-50 font-mono whitespace-pre-wrap break-words">
          {sql}
        </pre>
      )}
    </div>
  )
}

// ── Chart availability check ───────────────────────────────────────────────────

function hasNumericColumn(rows: Row[]): boolean {
  if (rows.length === 0) return false
  const keys = Object.keys(rows[0])
  return keys.some((k) => {
    const vals = rows.map((r) => r[k]).filter((v) => v != null && v !== '')
    return vals.length > 0 && vals.every((v) => !isNaN(Number(v)))
  })
}

// ── Main block ─────────────────────────────────────────────────────────────────

export function SqlResultsBlock({ rows, sql, answerText }: SqlResultsBlockProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<'table' | 'chart'>('table')

  const hasRows = rows.length > 0
  // Chart tab only shown when there are numeric columns to visualise
  const hasChart = rows.length >= 2 && hasNumericColumn(rows)
  const hasSql = !!sql?.trim()

  if (!hasRows && !hasSql) return null

  return (
    <div className="mt-3 space-y-2 w-full">
      {/* Results header + copy answer */}
      {hasRows && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1 rounded-lg bg-gray-100 p-0.5">
            <button
              onClick={() => setActiveTab('table')}
              className={cn(
                'flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors',
                activeTab === 'table'
                  ? 'bg-white text-gray-800 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700',
              )}
            >
              <Table2 className="h-3.5 w-3.5" />
              {t('results_table')}
              <span className="ml-0.5 rounded-full bg-gray-200 px-1.5 text-[10px] text-gray-600">
                {rows.length}
              </span>
            </button>
            {hasChart && (
              <button
                onClick={() => setActiveTab('chart')}
                className={cn(
                  'flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors',
                  activeTab === 'chart'
                    ? 'bg-white text-gray-800 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700',
                )}
              >
                <BarChart2 className="h-3.5 w-3.5" />
                {t('results_chart')}
              </button>
            )}
          </div>

          {answerText && <CopyButton text={answerText} labelKey="results_copy_answer" />}
        </div>
      )}

      {/* Tab content */}
      {hasRows && activeTab === 'table' && <DataTable rows={rows} />}
      {hasRows && activeTab === 'chart' && hasChart && <AutoChart rows={rows} />}

      {/* SQL collapsible */}
      {hasSql && <SqlBlock sql={sql!} />}
    </div>
  )
}
