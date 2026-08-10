import { ArrowUp, Check, History, Loader2, Lock } from 'lucide-react'

import type { DataProductLifecycle } from '@/api/types'
import { MenuDropdown, type MenuItem } from '@/components/ui/MenuDropdown'
import { StatusPill } from './StatusPill'
import { computeDeploymentState, type DeploymentState } from './deploymentState'

/**
 * Deployment & Versions panel (UX_CHANGES audit §6 / CH-4, fig. 4+5).
 *
 * Per-DataProduct release state: a working-draft row (when In Review) + a dev
 * row + a prod row, each with its version, a server-state badge, and the
 * env publish button. Gates per §6.3:
 *   - dev   "current" (dev.sha == main.sha) → disabled "Up to date";
 *            else amber "behind working" → "Publish to dev".
 *   - prod  no dev publish → "waiting on dev" (locked, tip "Publish to dev first");
 *            prod.sha == dev.sha → disabled "Up to date";
 *            else amber "behind" → "Publish to prod".
 *
 * Pure derivation lives in ./deploymentState (computeDeploymentState).
 */

function fmtAt(at?: string): string {
  return at ? at.slice(0, 10) : ''
}

function metaLine(at?: string, by?: string | null): string {
  // "current · 2026-06-09 · admin@example.com" — drop empty segments so we
  // never render dangling "· ·" when the backend omits at/by.
  return ['current', fmtAt(at) || null, by || null].filter(Boolean).join(' · ')
}

function prodNote(s: DeploymentState, prod: { version: number; at?: string; by?: string } | null): string {
  if (s.prod.state === 'waiting-on-dev') return 'waiting on dev'
  if (s.prod.state === 'up-to-date') return metaLine(prod?.at, prod?.by)
  if (s.prod.state === 'never') return 'ready for first prod publish'
  // behind: report the real version gap (dev ahead of prod), not a hardcoded 1.
  const dv = s.dev.version
  const pv = s.prod.version
  if (dv != null && pv != null) {
    const gap = dv - pv
    return `${gap} version${gap === 1 ? '' : 's'} behind`
  }
  return 'behind dev'
}

interface Props {
  lifecycle: DataProductLifecycle
  publishing: 'dev' | 'prod' | null
  onPublish: (env: 'dev' | 'prod') => void
  /** Open the version history (working/dev/prod) for this entity. */
  onHistory?: () => void
  /** Diff the workspace against what is published to an environment. Surfaced
   *  per-env in the row's ⋯ menu — the action lives next to its environment. */
  onDiff?: (env: 'dev' | 'prod') => void
  /** Unpublish (physically remove) the entity from an env — inverse of publish.
   *  Surfaced as a destructive ⋯ item, only when that env is published. */
  onUnpublish?: (env: 'dev' | 'prod') => void
}

export function DeploymentPanel({
  lifecycle,
  publishing,
  onPublish,
  onHistory,
  onDiff,
  onUnpublish,
}: Props) {
  const s = computeDeploymentState(lifecycle)
  const dev = lifecycle.dev_published
  const prod = lifecycle.prod_published

  // Per-env ⋯ items: Diff (when available) + a destructive Unpublish shown only
  // when that env is published. Dev's unpublish is gated while prod is still
  // published (mirror of the backend prod-before-dev gate).
  const devItems: MenuItem[] = [
    ...(onDiff ? [{ label: 'Diff vs dev', onClick: () => onDiff('dev') }] : []),
    ...(onUnpublish && dev
      ? [
          {
            label: prod ? 'Unpublish from dev — unpublish prod first' : 'Unpublish from dev',
            tone: 'danger' as const,
            disabled: !!prod,
            onClick: () => onUnpublish('dev'),
          },
        ]
      : []),
  ]
  const prodItems: MenuItem[] = [
    ...(onDiff ? [{ label: 'Diff vs prod', onClick: () => onDiff('prod') }] : []),
    ...(onUnpublish && prod
      ? [{ label: 'Unpublish from prod', tone: 'danger' as const, onClick: () => onUnpublish('prod') }]
      : []),
  ]

  return (
    <div className="rounded-md border border-gray-200 bg-white">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
          Environments
        </span>
        <div className="flex items-center gap-2">
          <StatusPill status={lifecycle.status} />
          {onHistory && (
            <button
              onClick={onHistory}
              title="Version history across Working / dev / prod"
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
            >
              <History size={12} />
              History
            </button>
          )}
        </div>
      </div>

      <div className="divide-y divide-gray-100">
        {/* Working draft — only when In Review (§6.3). */}
        {s.workingIsDraft && (
          <Row
            label="Working"
            versionChip={
              <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold border bg-teal-50 text-teal-700 border-teal-200">
                v{s.workingVersion} · draft
              </span>
            }
            note="not published yet"
            icon={<span className="h-1.5 w-1.5 rounded-full bg-teal-500" />}
          />
        )}

        {/* dev */}
        <Row
          label="dev"
          versionChip={
            dev ? (
              <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold border bg-blue-50 text-blue-700 border-blue-200">
                v{dev.version}
              </span>
            ) : (
              <span className="text-[10px] text-gray-400">not deployed</span>
            )
          }
          note={s.dev.state === 'current' ? metaLine(dev?.at, dev?.by) : 'behind working'}
          icon={
            s.dev.state === 'current' ? (
              <Check className="h-3 w-3 text-green-600" />
            ) : (
              <ArrowUp className="h-3 w-3 text-amber-500" />
            )
          }
          action={
            <PublishBtn
              label={s.dev.state === 'current' ? 'Up to date' : 'Publish to dev'}
              tone="blue"
              disabled={!s.dev.canPublish || publishing !== null}
              loading={publishing === 'dev'}
              onClick={() => onPublish('dev')}
            />
          }
          menu={
            devItems.length ? (
              <MenuDropdown title="More dev actions" items={devItems} />
            ) : undefined
          }
        />

        {/* prod */}
        <Row
          label="prod"
          versionChip={
            prod ? (
              <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold border bg-red-50 text-red-700 border-red-200">
                v{prod.version}
              </span>
            ) : (
              <span className="text-[10px] text-gray-400">not deployed</span>
            )
          }
          note={prodNote(s, prod)}
          icon={
            s.prod.state === 'up-to-date' ? (
              <Check className="h-3 w-3 text-green-600" />
            ) : s.prod.state === 'waiting-on-dev' ? (
              <Lock className="h-3 w-3 text-gray-400" />
            ) : (
              <ArrowUp className="h-3 w-3 text-amber-500" />
            )
          }
          action={
            <PublishBtn
              label={
                s.prod.state === 'waiting-on-dev'
                  ? 'Publish to dev first'
                  : s.prod.state === 'up-to-date'
                    ? 'Up to date'
                    : 'Publish to prod'
              }
              tone="green"
              disabled={!s.prod.canPublish || publishing !== null}
              loading={publishing === 'prod'}
              onClick={() => onPublish('prod')}
            />
          }
          menu={
            prodItems.length ? (
              <MenuDropdown title="More prod actions" items={prodItems} />
            ) : undefined
          }
        />
      </div>
    </div>
  )
}

function Row({
  label,
  versionChip,
  note,
  icon,
  action,
  menu,
}: {
  label: string
  versionChip: React.ReactNode
  note: string
  icon: React.ReactNode
  action?: React.ReactNode
  menu?: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-2">
      <span className="w-10 shrink-0 text-[11px] font-semibold text-gray-600">{label}</span>
      <span className="shrink-0">{icon}</span>
      <div className="min-w-0 flex-1 flex items-center gap-2">
        {versionChip}
        <span className="truncate text-[10px] text-gray-400">{note}</span>
      </div>
      {action}
      {menu}
    </div>
  )
}

function PublishBtn({
  label,
  tone,
  disabled,
  loading,
  onClick,
}: {
  label: string
  tone: 'blue' | 'green'
  disabled: boolean
  loading: boolean
  onClick: () => void
}) {
  const enabledCls =
    tone === 'green'
      ? 'border-green-300 text-green-700 hover:bg-green-50'
      : 'border-blue-300 text-blue-700 hover:bg-blue-50'
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      title={label}
      className={`shrink-0 inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
        disabled ? 'border-gray-200 text-gray-400' : enabledCls
      }`}
    >
      {loading && <Loader2 className="h-3 w-3 animate-spin" />}
      {label}
    </button>
  )
}
