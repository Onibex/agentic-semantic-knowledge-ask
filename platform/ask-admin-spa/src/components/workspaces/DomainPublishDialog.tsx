/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Domain publish dialog — two phases in one modal:
 *
 *  1. PLAN    — a checklist of the Data Products that have changes pending for
 *               the target env (all checked by default; deselect to skip).
 *  2. PROGRESS — streams the publish one DP at a time, showing which one is
 *               publishing *now*, which already finished (✓ / skipped / error),
 *               a progress bar, and a Stop button to abort if something hangs.
 *
 * This replaces the old fire-and-wait blocking publish whose single response
 * gave zero visibility — if one DP hung, the whole batch looked like a dead
 * console. The per-DP NDJSON stream from the backend fixes that.
 *
 * Hand-rolled modal (not the Radix Dialog) so dismissal can be locked while a
 * publish is in flight — matches the existing result-modal pattern in the
 * workspace pages.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  CheckSquare,
  Circle,
  Loader2,
  MinusCircle,
  Rocket,
  Square,
  XCircle,
} from 'lucide-react'
import { toast } from 'sonner'

import { publishDomainToEnvStream } from '../../api/client'
import type { DataProductLifecycle } from '../../api/types'
import { buildPublishCandidates } from '../../lib/domainPublish'

type RowStatus = 'pending' | 'publishing' | 'published' | 'skipped' | 'error' | 'stopped'
interface RowState {
  status: RowStatus
  reason: string | null
  sha: string | null
}

interface DomainPublishDialogProps {
  open: boolean
  env: 'dev' | 'prod'
  businessDomainId: string
  businessDomainName: string
  /** The domain's member entity ids (bd.data_product_ids). */
  members: string[]
  /** Lifecycle by entity id — drives the gate (eligible vs skipped). */
  lifecycleById: Map<string, DataProductLifecycle>
  /** Optional display names (entity id → name). */
  nameById?: Map<string, string>
  onClose: () => void
  /** Called once the run settles (done / aborted / failed) so the parent can
   *  refresh lifecycle caches — partial progress still landed. */
  onComplete?: (summary: { published: number; skipped: number; failed: number }) => void
}

export function DomainPublishDialog({
  open,
  env,
  businessDomainId,
  businessDomainName,
  members,
  lifecycleById,
  nameById,
  onClose,
  onComplete,
}: DomainPublishDialogProps) {
  const candidates = useMemo(
    () => buildPublishCandidates(members, lifecycleById, env, nameById),
    [members, lifecycleById, env, nameById],
  )
  const eligible = useMemo(() => candidates.filter((c) => c.eligible), [candidates])
  const skippedPreview = useMemo(() => candidates.filter((c) => !c.eligible), [candidates])

  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [phase, setPhase] = useState<'plan' | 'running' | 'done'>('plan')
  const [rows, setRows] = useState<Record<string, RowState>>({})
  const [order, setOrder] = useState<string[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const wasOpen = useRef(false)

  // Initialise ONLY on the false→true open transition. A lifecycle refetch
  // (which onComplete triggers) changes `eligible` mid-run — we must not let
  // that reset the progress view back to the plan.
  useEffect(() => {
    if (open && !wasOpen.current) {
      setPhase('plan')
      setRows({})
      setOrder([])
      setSelected(Object.fromEntries(eligible.map((c) => [c.entityId, true])))
    }
    wasOpen.current = open
  }, [open, eligible])

  if (!open) return null

  const selectedIds = eligible.filter((c) => selected[c.entityId]).map((c) => c.entityId)
  const allSelected = eligible.length > 0 && selectedIds.length === eligible.length
  const nameOf = (id: string) => nameById?.get(id) ?? id

  const total = order.length
  const completed = order.filter((id) => {
    const s = rows[id]?.status
    return s === 'published' || s === 'skipped' || s === 'error' || s === 'stopped'
  }).length
  const published = order.filter((id) => rows[id]?.status === 'published').length
  const skipped = order.filter((id) => rows[id]?.status === 'skipped').length
  const failed = order.filter((id) => rows[id]?.status === 'error').length
  const pct = total ? Math.round((completed / total) * 100) : 0

  function toggleAll() {
    const next = !allSelected
    setSelected(Object.fromEntries(eligible.map((c) => [c.entityId, next])))
  }

  async function start() {
    const ids = selectedIds
    if (ids.length === 0) return
    setOrder(ids)
    setRows(Object.fromEntries(ids.map((id) => [id, { status: 'pending', reason: null, sha: null }])))
    setPhase('running')
    const ac = new AbortController()
    abortRef.current = ac
    let summary = { published: 0, skipped: 0, failed: 0 }
    try {
      for await (const ev of publishDomainToEnvStream(businessDomainId, env, ids, ac.signal)) {
        if (ev.type === 'processing') {
          setRows((p) => ({
            ...p,
            [ev.entity_id]: { status: 'publishing', reason: null, sha: p[ev.entity_id]?.sha ?? null },
          }))
        } else if (ev.type === 'item') {
          setRows((p) => ({
            ...p,
            [ev.entity_id]: { status: ev.outcome, reason: ev.reason, sha: ev.committed_sha },
          }))
        } else if (ev.type === 'done') {
          summary = { published: ev.published, skipped: ev.skipped, failed: ev.failed }
        }
      }
    } catch (err) {
      if (ac.signal.aborted) {
        // Flag whatever hadn't finished so it's clear what did NOT publish.
        setRows((p) => {
          const next = { ...p }
          for (const id of ids) {
            const s = next[id]?.status
            if (s === 'pending' || s === 'publishing') {
              next[id] = { status: 'stopped', reason: 'stopped by user', sha: null }
            }
          }
          return next
        })
      } else {
        toast.error(err instanceof Error ? err.message : `Publish → ${env} failed`)
      }
    } finally {
      abortRef.current = null
      setPhase('done')
      onComplete?.(summary)
    }
  }

  function requestClose() {
    if (phase === 'running') return // locked — use Stop first
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={requestClose}
    >
      <div
        className="flex max-h-[82vh] w-full max-w-lg flex-col rounded-lg border border-gray-200 bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-200 p-4">
          <div className="min-w-0">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
              <Rocket className="h-4 w-4 text-gray-500" />
              {phase === 'plan' ? 'Publish domain' : 'Publishing domain'} →{' '}
              <span className={env === 'prod' ? 'text-emerald-700' : 'text-blue-700'}>{env}</span>
            </h3>
            <p className="mt-0.5 truncate text-[11px] text-gray-500">{businessDomainName}</p>
          </div>
          {phase !== 'running' && (
            <button
              onClick={onClose}
              className="text-xl leading-none text-gray-400 hover:text-gray-600"
              aria-label="Close"
            >
              ×
            </button>
          )}
        </div>

        {/* ── PLAN ─────────────────────────────────────────────────────────── */}
        {phase === 'plan' && (
          <>
            <div className="border-b border-gray-100 px-4 py-2">
              {eligible.length === 0 ? (
                <p className="py-1 text-xs text-gray-500">
                  Nothing to {env === 'prod' ? 'promote' : 'publish'} — everything is up to date.
                </p>
              ) : (
                <div className="flex items-center justify-between">
                  <button
                    onClick={toggleAll}
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-900"
                  >
                    {allSelected ? (
                      <CheckSquare className="h-3.5 w-3.5" />
                    ) : (
                      <Square className="h-3.5 w-3.5" />
                    )}
                    {allSelected ? 'Deselect all' : 'Select all'}
                  </button>
                  <span className="text-[11px] text-gray-500">
                    {selectedIds.length} of {eligible.length} selected
                  </span>
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              <ul className="space-y-0.5">
                {eligible.map((c) => (
                  <li key={c.entityId}>
                    <label className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-gray-50">
                      <input
                        type="checkbox"
                        checked={!!selected[c.entityId]}
                        onChange={(e) =>
                          setSelected((p) => ({ ...p, [c.entityId]: e.target.checked }))
                        }
                        className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                      <span className="min-w-0 flex-1 truncate text-xs text-gray-800">
                        {nameOf(c.entityId)}
                      </span>
                      {nameById?.get(c.entityId) && (
                        <code className="shrink-0 truncate font-mono text-[10px] text-gray-400">
                          {c.entityId}
                        </code>
                      )}
                    </label>
                  </li>
                ))}
              </ul>

              {skippedPreview.length > 0 && (
                <p
                  className="mt-2 border-t border-gray-100 pt-2 text-[11px] text-gray-400"
                  title={skippedPreview.map((c) => `${c.entityId} — ${c.skipReason}`).join('\n')}
                >
                  + {skippedPreview.length} not eligible (will be skipped)
                  {env === 'prod' &&
                    skippedPreview.some((c) => c.skipReason?.includes('dev')) && (
                      <span className="ml-1 text-amber-600">
                        — some need a dev publish first
                      </span>
                    )}
                </p>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-gray-200 p-3">
              <button
                onClick={onClose}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => void start()}
                disabled={selectedIds.length === 0}
                className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 ${
                  env === 'prod'
                    ? 'bg-emerald-600 hover:bg-emerald-700'
                    : 'bg-blue-600 hover:bg-blue-700'
                }`}
              >
                <Rocket className="h-3.5 w-3.5" />
                Publish {selectedIds.length} → {env}
              </button>
            </div>
          </>
        )}

        {/* ── PROGRESS / DONE ──────────────────────────────────────────────── */}
        {phase !== 'plan' && (
          <>
            <div className="border-b border-gray-100 px-4 py-3">
              <div className="mb-1 flex items-center justify-between text-[11px] text-gray-500">
                <span>
                  {completed} / {total} done
                </span>
                <span>
                  ✓ {published} published · {skipped} skipped
                  {failed ? ` · ⚠ ${failed} failed` : ''}
                </span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
                <div
                  className={`h-full rounded-full transition-all duration-300 ${
                    failed ? 'bg-amber-500' : env === 'prod' ? 'bg-emerald-500' : 'bg-blue-500'
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>

            <div className="flex-1 divide-y divide-gray-100 overflow-y-auto p-3">
              {order.map((id) => {
                const r = rows[id] ?? { status: 'pending', reason: null, sha: null }
                return (
                  <div key={id} className="flex items-center gap-2 py-1.5 text-xs">
                    <StatusIcon status={r.status} />
                    <span className="min-w-0 flex-1 truncate text-gray-800">{nameOf(id)}</span>
                    {r.sha && (
                      <code className="shrink-0 font-mono text-[10px] text-gray-400">
                        @{r.sha.slice(0, 7)}
                      </code>
                    )}
                    {r.reason && (
                      <span className="shrink-0 max-w-[45%] truncate text-[10px] text-gray-400">
                        {r.reason}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>

            <div className="flex items-center justify-between gap-2 border-t border-gray-200 p-3">
              {phase === 'running' ? (
                <>
                  <span className="inline-flex items-center gap-1.5 text-[11px] text-gray-500">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Publishing… you can keep this open to watch.
                  </span>
                  <button
                    onClick={() => abortRef.current?.abort()}
                    className="rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50"
                  >
                    Stop
                  </button>
                </>
              ) : (
                <>
                  <span className="inline-flex items-center gap-1.5 text-[11px] text-gray-500">
                    {failed > 0 && <AlertTriangle className="h-3 w-3 text-amber-500" />}
                    {failed > 0
                      ? `${failed} failed — review above.`
                      : 'Publish complete.'}
                  </span>
                  <button
                    onClick={onClose}
                    className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-700"
                  >
                    Done
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function StatusIcon({ status }: { status: RowStatus }) {
  switch (status) {
    case 'publishing':
      return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-600" />
    case 'published':
      return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-600" />
    case 'skipped':
      return <MinusCircle className="h-3.5 w-3.5 shrink-0 text-gray-400" />
    case 'error':
      return <XCircle className="h-3.5 w-3.5 shrink-0 text-red-600" />
    case 'stopped':
      return <MinusCircle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
    default:
      return <Circle className="h-3.5 w-3.5 shrink-0 text-gray-300" />
  }
}
