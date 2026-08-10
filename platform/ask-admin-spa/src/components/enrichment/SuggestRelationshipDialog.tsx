import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Info,
  Loader2,
  Sparkles,
  XCircle,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { suggestRelationshipComplete } from '@/api/client'
import type {
  RelationshipSuggestConfidence,
  RelationshipSuggestResponse,
  SuggestedRelationship,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/**
 * Modo 2 — Complete: SOURCE→TARGET both picked, ask the LLM for the join +
 * cardinality + cost. Three terminal states drive the UX:
 *
 *   high      → green banner, single Apply CTA
 *   medium    → amber banner with caveats list, Apply enabled
 *   low       → amber banner with caveats list + "Edit before applying" hint
 *   no-match  → red banner with no_match_reason, only "Switch to manual editing"
 *
 * Apply does NOT persist directly. It hands the proposal back to the caller
 * (RelationshipsEditor) which mixes it into the current relationship card
 * and lets the admin Save the Edit panel — keeping the editor flow as the
 * single source of truth for commits.
 */
interface Props {
  open: boolean
  onClose: () => void
  sourceEntityId: string
  targetEntityId: string
  workspaceId: string | null
  /** Called with the LLM proposal + caveats so the parent can pre-fill the card. */
  onApply: (suggestion: SuggestedRelationship, caveats: string[]) => void
  /** Called when the admin gives up on the suggestion and wants to type SQL by hand. */
  onSwitchToManual: () => void
}

export function SuggestRelationshipDialog({
  open,
  onClose,
  sourceEntityId,
  targetEntityId,
  workspaceId,
  onApply,
  onSwitchToManual,
}: Props) {
  const [data, setData] = useState<RelationshipSuggestResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)
    suggestRelationshipComplete({
      source_entity_id: sourceEntityId,
      target_entity_id: targetEntityId,
      workspace_id: workspaceId,
    })
      .then((resp) => {
        if (cancelled) return
        setData(resp)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load suggestion')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, sourceEntityId, targetEntityId, workspaceId])

  function handleApply() {
    if (!data?.relationship) return
    onApply(data.relationship, data.caveats)
    toast.success('Suggestion applied to the relationship card')
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles size={16} className="text-violet-600" />
            Suggest relationship details
          </DialogTitle>
          <DialogDescription>
            From <code className="font-mono">{sourceEntityId}</code>{' '}
            <ArrowRight size={11} className="inline mx-0.5" />{' '}
            <code className="font-mono">{targetEntityId}</code>. The model proposes the
            join + cardinality + cost; you decide whether to apply.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto -mx-6 px-6">
          {loading && (
            <div className="flex flex-col items-center justify-center py-16 text-gray-500 gap-3">
              <Loader2 size={20} className="animate-spin" />
              <div className="text-sm">Asking the model…</div>
              <div className="text-xs text-gray-400">
                Sending only PKs + FK-shaped fields, not the full YAML.
              </div>
            </div>
          )}

          {error && !loading && (
            <div className="px-3 py-2 rounded-md bg-red-50 border border-red-200 text-sm text-red-900">
              {error}
            </div>
          )}

          {data && !loading && <Outcome data={data} />}
        </div>

        <DialogFooter className="border-t border-gray-100 pt-3 mt-2">
          {data?.relationship ? (
            <>
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button
                onClick={handleApply}
                className={
                  data.confidence === 'high'
                    ? 'bg-emerald-600 hover:bg-emerald-700'
                    : 'bg-amber-600 hover:bg-amber-700'
                }
              >
                {data.confidence === 'high' ? 'Apply' : 'Apply with caveats'}
              </Button>
            </>
          ) : data ? (
            <>
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  onSwitchToManual()
                  onClose()
                }}
              >
                Switch to manual editing
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={onClose} disabled={loading}>
              Cancel
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Outcome renderers ──────────────────────────────────────────────────────

function Outcome({ data }: { data: RelationshipSuggestResponse }) {
  if (!data.relationship) {
    return <NoMatchOutcome data={data} />
  }
  return <SuggestionOutcome data={data} />
}

function SuggestionOutcome({ data }: { data: RelationshipSuggestResponse }) {
  const rel = data.relationship!
  const tone = TONE[data.confidence]
  return (
    <div className="flex flex-col gap-3 py-2">
      {/* Confidence banner */}
      <div className={`rounded-md border px-3 py-2 flex items-start gap-2 ${tone.bg}`}>
        {data.confidence === 'high' ? (
          <CheckCircle2 size={14} className={`mt-0.5 shrink-0 ${tone.text}`} />
        ) : (
          <AlertTriangle size={14} className={`mt-0.5 shrink-0 ${tone.text}`} />
        )}
        <div className="text-xs">
          <div className={`font-semibold ${tone.text}`}>{tone.title}</div>
          <div className={tone.subtext}>{tone.subtitle}</div>
        </div>
      </div>

      {/* The relationship body — compact, read-only preview */}
      <section className="border border-gray-200 rounded-md">
        <header className="px-3 py-1.5 border-b border-gray-200 bg-gray-50 text-[10px] font-semibold uppercase tracking-wider text-gray-600">
          Proposed relationship
        </header>
        <dl className="px-3 py-2 grid grid-cols-3 gap-x-3 gap-y-1.5 text-xs">
          <Row label="target" value={rel.target_entity} mono />
          <Row label="type" value={rel.relationship_type ?? '—'} />
          <Row label="cost" value={rel.traversal_cost?.toString() ?? '—'} />
          <Row label="label" value={rel.semantic_label ?? '—'} />
          <Row label="safety" value={rel.aggregation_safety ?? '—'} />
          <Row label="cross-module" value={rel.cross_module ? 'yes' : 'no'} />
        </dl>
        <div className="px-3 pb-2 text-[11px] text-gray-700">
          <span className="font-medium text-gray-500">join:</span>{' '}
          <code className="font-mono text-[10px] bg-gray-50 border border-gray-200 rounded px-1 py-0.5">
            {rel.join_condition ?? '—'}
          </code>
        </div>
        {rel.description && (
          <div className="px-3 pb-2 text-[11px] text-gray-700">
            <span className="font-medium text-gray-500">description:</span> {rel.description}
          </div>
        )}
      </section>

      {/* Caveats */}
      {data.caveats.length > 0 && (
        <section className="border border-amber-200 bg-amber-50/60 rounded-md">
          <header className="px-3 py-1.5 border-b border-amber-200 text-[10px] font-semibold uppercase tracking-wider text-amber-800 flex items-center gap-1">
            <Info size={11} />
            Decision notes ({data.caveats.length})
          </header>
          <ul className="px-3 py-2 space-y-1 text-[11px] text-amber-900">
            {data.caveats.map((c, i) => (
              <li key={i} className="leading-snug">
                • {c}
              </li>
            ))}
          </ul>
          <div className="px-3 pb-2 text-[10px] text-amber-700/80">
            These notes are persisted in the git commit message — they live in{' '}
            <code className="font-mono">git log</code>, not in the YAML.
          </div>
        </section>
      )}

      {/* Token/provider footer */}
      <div className="text-[10px] text-gray-400 flex justify-between">
        <span>
          {data.provider} · {data.model || '—'}
        </span>
        <span>
          {data.tokens_used.toLocaleString()} tokens · {data.elapsed_ms} ms
        </span>
      </div>
    </div>
  )
}

function NoMatchOutcome({ data }: { data: RelationshipSuggestResponse }) {
  return (
    <div className="flex flex-col gap-3 py-2">
      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 flex items-start gap-2">
        <XCircle size={14} className="mt-0.5 shrink-0 text-red-600" />
        <div className="text-xs">
          <div className="font-semibold text-red-800">No suggestion possible</div>
          <div className="text-red-700/90 mt-0.5">
            {data.no_match_reason ||
              'The model could not find a confident FK match between these two entities.'}
          </div>
        </div>
      </div>

      {data.diagnostic?.parse_error && (
        <div className="text-[10px] font-mono text-gray-500 bg-gray-50 border border-gray-200 rounded px-2 py-1.5">
          <div className="font-semibold text-gray-600 mb-0.5">Parse error</div>
          <div className="whitespace-pre-wrap break-words">{data.diagnostic.parse_error}</div>
        </div>
      )}

      <div className="text-xs text-gray-600">
        You can still define the join manually — click <strong>Switch to manual editing</strong>{' '}
        below to open the relationship card with the target pre-filled and the join condition
        empty.
      </div>

      <div className="text-[10px] text-gray-400 flex justify-between">
        <span>
          {data.provider} · {data.model || '—'}
        </span>
        <span>
          {data.tokens_used.toLocaleString()} tokens · {data.elapsed_ms} ms
        </span>
      </div>
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <>
      <dt className="col-span-1 text-[10px] uppercase tracking-wider text-gray-500">{label}</dt>
      <dd
        className={`col-span-2 text-gray-800 ${mono ? 'font-mono text-[11px]' : ''} truncate`}
        title={value}
      >
        {value}
      </dd>
    </>
  )
}

// Per-confidence colour + copy lookup. Centralised so the three branches
// stay consistent — easy to tune later without hunting through JSX.
const TONE: Record<
  RelationshipSuggestConfidence,
  { bg: string; text: string; subtext: string; title: string; subtitle: string }
> = {
  high: {
    bg: 'bg-emerald-50 border-emerald-200',
    text: 'text-emerald-800',
    subtext: 'text-emerald-700/80',
    title: 'High confidence',
    subtitle: 'FK pattern is clear; the model is confident in every field.',
  },
  medium: {
    bg: 'bg-amber-50 border-amber-200',
    text: 'text-amber-800',
    subtext: 'text-amber-700/80',
    title: 'Medium confidence',
    subtitle: 'Best of multiple plausible options. Review the decision notes below.',
  },
  low: {
    bg: 'bg-amber-50 border-amber-200',
    text: 'text-amber-800',
    subtext: 'text-amber-700/80',
    title: 'Low confidence — verify',
    subtitle: 'Decision based on partial information. Review notes before applying.',
  },
}
