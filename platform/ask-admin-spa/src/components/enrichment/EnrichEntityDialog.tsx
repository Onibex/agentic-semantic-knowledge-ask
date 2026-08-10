import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Code2,
  Info,
  Loader2,
  Sparkles,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import {
  getEnrichmentScopeDefaults,
  previewEntityEnrichment,
  updateYaml,
} from '@/api/client'
import type {
  EnrichEntityResponse,
  EnrichEntityScopeDefaults,
  YAMLNode,
  YAMLUpdateRequest,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useAuthStore } from '@/store/authStore'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { PromptPreviewDialog } from './PromptPreviewDialog'

/**
 * Two-step AI-assisted enrichment for an entity YAML.
 *
 *   Step 1 — Scope checklist:
 *     [✓] Entity description       Sales order header (good)
 *     [✓] netwr_vbak — Net value          (short)
 *     [✓] kunnr_vbak — empty              (empty)
 *     [ ] vbeln_vbak — Sales document     (good)
 *     ⊘  mandt_vbak — SKIPPED (system)
 *     [Cancel] [Generate]
 *
 *   Step 2 — Diff preview (all-or-nothing apply):
 *     Provider · Nova Lite · 4,231 tokens
 *     entity.description   "Sales order header"
 *                       ▸ "Sales order header with billing context"
 *     netwr_vbak description  "Net value"
 *                          ▸ "Net monetary amount of the line"
 *     netwr_vbak synonyms     []
 *                          ▸ [amount, value, total]
 *     [Back] [Cancel] [Apply X changes]
 */

interface Props {
  open: boolean
  entity: YAMLNode
  onClose: () => void
  /** Triggered after a successful Apply so the parent can refetch the node. */
  onApplied: () => void
}

type Stage = 'scope' | 'previewing' | 'preview' | 'applying'

export function EnrichEntityDialog({ open, entity, onClose, onApplied }: Props) {
  const user = useAuthStore((s) => s.user)
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)
  const [stage, setStage] = useState<Stage>('scope')
  const [defaults, setDefaults] = useState<EnrichEntityScopeDefaults | null>(null)
  const [entityLevelSelected, setEntityLevelSelected] = useState(false)
  const [fieldsSelected, setFieldsSelected] = useState<Set<string>>(new Set())
  const [diff, setDiff] = useState<EnrichEntityResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Read-only "what the model will see" inspector — opens a sibling dialog.
  const [promptPreviewOpen, setPromptPreviewOpen] = useState(false)

  // ─ Load checklist defaults on open ───────────────────────────────────────
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setStage('scope')
    setError(null)
    setDiff(null)
    // Pass the active workspace so the response embeds the same workspace
    // framing the preview endpoint would inject — admin sees it before
    // spending tokens.
    getEnrichmentScopeDefaults(entity.id, activeWorkspaceId)
      .then((d) => {
        if (cancelled) return
        setDefaults(d)
        setEntityLevelSelected(d.default_selection.entity_level)
        setFieldsSelected(new Set(d.default_selection.field_names))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : 'Could not load scope'
        setError(msg)
      })
    return () => {
      cancelled = true
    }
  }, [open, entity.id, activeWorkspaceId])

  const enrichableSelectedCount = useMemo(
    () => fieldsSelected.size + (entityLevelSelected ? 1 : 0),
    [fieldsSelected, entityLevelSelected],
  )

  // ─ Quick-actions ─────────────────────────────────────────────────────────
  const selectAll = useCallback(() => {
    if (!defaults) return
    setEntityLevelSelected(true)
    setFieldsSelected(new Set(defaults.enrichable_fields.map((f) => f.name)))
  }, [defaults])
  const selectNone = useCallback(() => {
    setEntityLevelSelected(false)
    setFieldsSelected(new Set())
  }, [])
  const selectEmpty = useCallback(() => {
    if (!defaults) return
    setEntityLevelSelected(!defaults.entity_level.has_description)
    setFieldsSelected(
      new Set(
        defaults.enrichable_fields
          .filter((f) => f.priority === 'empty')
          .map((f) => f.name),
      ),
    )
  }, [defaults])

  const toggleField = useCallback((name: string) => {
    setFieldsSelected((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])

  // ─ Generate (Step 1 → Step 2) ───────────────────────────────────────────
  const handleGenerate = useCallback(async () => {
    if (enrichableSelectedCount === 0) {
      toast.error('Select at least one item to enrich')
      return
    }
    setStage('previewing')
    setError(null)
    try {
      const result = await previewEntityEnrichment({
        entity_id: entity.id,
        scope: {
          entity_level: entityLevelSelected,
          field_names: Array.from(fieldsSelected),
        },
        // Pass the active workspace so the backend can inject DP + sibling
        // entity context into the prompt — sharpens the descriptions toward
        // how the entity is consumed in this specific workspace.
        workspace_id: activeWorkspaceId ?? null,
      })
      setDiff(result)
      setStage('preview')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Enrichment failed'
      setError(msg)
      setStage('scope')
      toast.error(msg)
    }
  }, [
    enrichableSelectedCount,
    entity.id,
    entityLevelSelected,
    fieldsSelected,
    activeWorkspaceId,
  ])

  // ─ Apply (Step 2 → PATCH /v1/viz/yamls/:id) ─────────────────────────────
  const handleApply = useCallback(async () => {
    if (!diff) return
    setStage('applying')
    setError(null)
    try {
      const payload = buildUpdatePayload(diff, user?.email)
      await updateYaml(entity.id, payload)
      toast.success('Enrichment applied')
      onApplied()
      onClose()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Apply failed'
      setError(msg)
      setStage('preview')
      toast.error(msg)
    }
  }, [diff, entity.id, user?.email, onApplied, onClose])

  // ─ Render ────────────────────────────────────────────────────────────────
  const inFlight = stage === 'previewing' || stage === 'applying'

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o && !inFlight) onClose()
      }}
    >
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles size={16} className="text-blue-600" />
            Edit with AI Assist — {entity.name}
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto -mx-6 px-6">
          {stage === 'scope' && (
            <ScopeStep
              defaults={defaults}
              entityLevelSelected={entityLevelSelected}
              fieldsSelected={fieldsSelected}
              onToggleEntity={() => setEntityLevelSelected((v) => !v)}
              onToggleField={toggleField}
              onSelectAll={selectAll}
              onSelectNone={selectNone}
              onSelectEmpty={selectEmpty}
            />
          )}
          {stage === 'previewing' && (
            <div className="flex flex-col items-center justify-center py-16 text-gray-500 gap-3">
              <Loader2 size={20} className="animate-spin" />
              <div className="text-sm">Generating enrichments…</div>
              <div className="text-xs text-gray-400">
                One LLM call · {enrichableSelectedCount} item
                {enrichableSelectedCount === 1 ? '' : 's'}
              </div>
            </div>
          )}
          {(stage === 'preview' || stage === 'applying') && diff && (
            <PreviewStep diff={diff} />
          )}
        </div>

        {error && (
          <div className="px-3 py-2 mt-2 rounded-md bg-red-50 border border-red-200 text-sm text-red-900">
            {error}
          </div>
        )}

        <DialogFooter className="border-t border-gray-100 pt-3 mt-2">
          {stage === 'scope' && (
            <>
              <Button
                variant="ghost"
                onClick={() => setPromptPreviewOpen(true)}
                disabled={enrichableSelectedCount === 0}
                className="mr-auto text-violet-700 hover:text-violet-800 hover:bg-violet-50"
                title="Inspect the exact (system + user) messages the model will receive — no LLM call, no tokens spent."
              >
                <Code2 size={12} className="mr-1.5" /> Show full prompt
              </Button>
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button
                onClick={() => void handleGenerate()}
                disabled={enrichableSelectedCount === 0}
              >
                Generate ({enrichableSelectedCount})
              </Button>
            </>
          )}
          {stage === 'previewing' && (
            <Button variant="outline" disabled>
              Generating…
            </Button>
          )}
          {stage === 'preview' && diff && (
            <>
              <Button variant="outline" onClick={() => setStage('scope')}>
                <ArrowLeft size={12} className="mr-1.5" /> Back
              </Button>
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button
                onClick={() => void handleApply()}
                disabled={!hasAnyChange(diff)}
              >
                Apply changes
              </Button>
            </>
          )}
          {stage === 'applying' && (
            <Button disabled>
              <Loader2 size={12} className="animate-spin mr-1.5" /> Applying…
            </Button>
          )}
        </DialogFooter>
      </DialogContent>

      {promptPreviewOpen && (
        <PromptPreviewDialog
          open
          onClose={() => setPromptPreviewOpen(false)}
          entityId={entity.id}
          scope={{
            entity_level: entityLevelSelected,
            field_names: Array.from(fieldsSelected),
          }}
          workspaceId={activeWorkspaceId ?? null}
        />
      )}
    </Dialog>
  )
}

// ── Step 1 ──────────────────────────────────────────────────────────────────

interface ScopeStepProps {
  defaults: EnrichEntityScopeDefaults | null
  entityLevelSelected: boolean
  fieldsSelected: Set<string>
  onToggleEntity: () => void
  onToggleField: (name: string) => void
  onSelectAll: () => void
  onSelectNone: () => void
  onSelectEmpty: () => void
}

function ScopeStep({
  defaults,
  entityLevelSelected,
  fieldsSelected,
  onToggleEntity,
  onToggleField,
  onSelectAll,
  onSelectNone,
  onSelectEmpty,
}: ScopeStepProps) {
  if (!defaults) {
    return (
      <div className="flex items-center justify-center py-12 text-gray-500">
        <Loader2 size={14} className="animate-spin mr-2" /> Loading scope…
      </div>
    )
  }

  return (
    <div className="space-y-4 py-2">
      {/* Workspace context — the bias the LLM will receive. Shown collapsed
          by default so the dialog isn't visually heavy, but always one click
          away. Absent when no workspace is active or the entity isn't part
          of any DP in the workspace. */}
      {defaults.workspace_context && (
        <ContextPanel context={defaults.workspace_context} />
      )}

      <p className="text-xs text-gray-600">
        Select what to enrich. Empty / short descriptions are pre-selected.
        Technical fields are excluded automatically.
      </p>

      {/* Entity-level — the "card" of the YAML itself (description / alias /
          business_process), feeds the agent's entity-level retrieval embedding. */}
      <section>
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
          Entity-level
          <span
            className="ml-1.5 text-gray-300 cursor-help"
            title="Top-level YAML metadata (description / alias / business_process). The agent uses these to PICK the entity when answering a question — distinct from field descriptions which are used to pick columns within an entity."
          >
            ⓘ
          </span>
        </h4>
        <label className="flex items-start gap-2 px-2 py-1.5 rounded border border-gray-200 hover:bg-gray-50 cursor-pointer">
          <input
            type="checkbox"
            checked={entityLevelSelected}
            onChange={onToggleEntity}
            className="mt-1"
          />
          <div className="flex-1 min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-800">
                Entity description, alias, business_process
              </span>
              <PriorityBadge priority={defaults.entity_level.priority} />
            </div>
            <EntityLevelCurrent scope={defaults.entity_level} />
          </div>
        </label>
      </section>

      {/* Enrichable fields */}
      <section>
        <div className="flex items-baseline justify-between mb-1.5">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
            Fields ({defaults.enrichable_fields.length} enrichable ·{' '}
            {defaults.technical_fields.length} excluded)
          </h4>
          <div className="flex gap-1.5 text-[11px]">
            <button
              type="button"
              className="text-blue-600 hover:underline"
              onClick={onSelectAll}
            >
              All
            </button>
            <span className="text-gray-300">|</span>
            <button
              type="button"
              className="text-blue-600 hover:underline"
              onClick={onSelectEmpty}
            >
              Empty only
            </button>
            <span className="text-gray-300">|</span>
            <button
              type="button"
              className="text-blue-600 hover:underline"
              onClick={onSelectNone}
            >
              None
            </button>
          </div>
        </div>

        <div className="border border-gray-200 rounded divide-y divide-gray-100 max-h-72 overflow-y-auto">
          {defaults.enrichable_fields.map((f) => (
            <label
              key={f.name}
              className="flex items-start gap-2 px-2 py-1.5 hover:bg-gray-50 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={fieldsSelected.has(f.name)}
                onChange={() => onToggleField(f.name)}
                className="mt-0.5"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-mono text-gray-800">{f.name}</span>
                  <PriorityBadge priority={f.priority} />
                  {f.is_likely_flag && (
                    <span
                      className="text-[9px] uppercase tracking-wide text-purple-700 bg-purple-100 rounded px-1 py-0.5"
                      title="Likely a boolean / status / flag field (matches patterns like is_*, *_flag, *_status, or SAP C1 type). These are short by design — the AI will keep the description terse if you enrich it. Not pre-selected."
                    >
                      flag?
                    </span>
                  )}
                  {!f.has_synonyms && !f.is_likely_flag && (
                    <span className="text-[9px] uppercase tracking-wide text-amber-700 bg-amber-100 rounded px-1 py-0.5">
                      no synonyms
                    </span>
                  )}
                </div>
                {f.current_description && (
                  <div className="text-[11px] text-gray-500 truncate">
                    {f.current_description}
                  </div>
                )}
              </div>
            </label>
          ))}
          {defaults.enrichable_fields.length === 0 && (
            <p className="text-xs text-gray-400 italic px-2 py-3">
              No enrichable fields — every field is either technical (audit / system)
              or has no name.
            </p>
          )}
        </div>

        {defaults.technical_fields.length > 0 && (
          <details className="mt-1.5 text-[11px] text-gray-500">
            <summary className="cursor-pointer hover:text-gray-700">
              Excluded technical fields ({defaults.technical_fields.length})
            </summary>
            <div className="mt-1 font-mono px-2 text-gray-400 break-words">
              {defaults.technical_fields.join(', ')}
            </div>
          </details>
        )}
      </section>
    </div>
  )
}

function ContextPanel({ context }: { context: string }) {
  // Collapsed by default so the dialog isn't dense; one click reveals the
  // exact framing the LLM will receive (workspace objective + Data Products
  // + sibling entities). Transparency over magic.
  const [expanded, setExpanded] = useState(false)
  // First line is usually the workspace label — use it as the teaser.
  const teaser = context.split('\n', 1)[0] || 'Workspace context available'
  return (
    <div className="border border-blue-200 bg-blue-50/60 rounded-md">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-blue-50 rounded-md"
      >
        {expanded ? (
          <ChevronDown size={14} className="text-blue-700 shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-blue-700 shrink-0" />
        )}
        <Info size={13} className="text-blue-600 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-medium text-blue-900">
            Context the AI will use
          </div>
          {!expanded && (
            <div className="text-[11px] text-blue-700 truncate">{teaser}</div>
          )}
        </div>
      </button>
      {expanded && (
        <div className="px-3 pb-3 -mt-1">
          <pre className="text-[11px] text-blue-900 whitespace-pre-wrap font-sans leading-snug bg-white border border-blue-100 rounded px-2.5 py-2">
            {context}
          </pre>
          <p className="mt-1.5 text-[10px] text-blue-700/80">
            Sent verbatim to the model alongside the YAML so descriptions and
            synonyms align with how this entity is consumed in this workspace.
          </p>
        </div>
      )}
    </div>
  )
}

function EntityLevelCurrent({
  scope,
}: {
  scope: EnrichEntityScopeDefaults['entity_level']
}) {
  // Mirror the per-field row's "current value" preview, but for the three
  // entity-level keys at once. Missing keys show as "(empty)" so the admin
  // can see at a glance which ones the LLM will draft from scratch.
  const rows: Array<{ key: string; value: string }> = [
    { key: 'description', value: scope.current_description },
    { key: 'alias', value: scope.current_alias },
    { key: 'business_process', value: scope.current_business_process },
  ]
  return (
    <div className="text-[11px] text-gray-500 space-y-0.5">
      {rows.map((row) => (
        <div key={row.key} className="flex gap-1.5">
          <span className="font-mono text-gray-400 shrink-0">{row.key}:</span>
          {row.value ? (
            <span className="text-gray-600 truncate">{row.value}</span>
          ) : (
            <span className="italic text-gray-400">(empty — AI will draft)</span>
          )}
        </div>
      ))}
    </div>
  )
}

function PriorityBadge({ priority }: { priority: 'empty' | 'short' | 'good' }) {
  const styles: Record<string, string> = {
    empty: 'bg-red-100 text-red-700',
    short: 'bg-amber-100 text-amber-700',
    good: 'bg-emerald-100 text-emerald-700',
  }
  const label = priority === 'empty' ? 'EMPTY' : priority === 'short' ? 'SHORT' : 'GOOD'
  return (
    <span
      className={`text-[9px] uppercase tracking-wide rounded px-1 py-0.5 ${styles[priority]}`}
    >
      {label}
    </span>
  )
}

// ── Step 2 ──────────────────────────────────────────────────────────────────

function PreviewStep({ diff }: { diff: EnrichEntityResponse }) {
  const totalChanges = countChanges(diff)
  const caveats = diff.caveats ?? []
  return (
    <div className="space-y-4 py-2">
      <div className="flex items-center justify-between text-[11px] text-gray-500">
        <span>
          {diff.provider} · {diff.model || '—'} · {diff.tokens_used.toLocaleString()}{' '}
          tokens · {diff.elapsed_ms} ms
        </span>
        <span>
          {totalChanges} change{totalChanges === 1 ? '' : 's'} proposed
          {caveats.length > 0 && (
            <span className="ml-1 text-amber-700">
              · {caveats.length} kept
            </span>
          )}
        </span>
      </div>

      {/* Preservation-guard caveats — the backend cancelled rewrites that
          would have dropped value mappings / source citations. Show them
          upfront so the admin understands why some fields don't appear in
          the diff below. */}
      {caveats.length > 0 && (
        <section className="border border-amber-200 bg-amber-50/60 rounded-md">
          <header className="px-3 py-1.5 border-b border-amber-200 text-[10px] font-semibold uppercase tracking-wider text-amber-800 flex items-center gap-1">
            <Info size={11} />
            Preserved by the guard ({caveats.length})
          </header>
          <ul className="px-3 py-2 space-y-1 text-[11px] text-amber-900">
            {caveats.map((c, i) => (
              <li key={i} className="leading-snug">
                • {c}
              </li>
            ))}
          </ul>
          <div className="px-3 pb-2 text-[10px] text-amber-700/80">
            These descriptions already carry value mappings (<code>'C' = CLOSE</code>)
            or source citations (<code>VBAK.NETWR</code>). The AI's rewrite
            would have dropped them, so the original stays. Edit manually if
            you really want a different wording.
          </div>
        </section>
      )}

      {/* Entity-level diffs */}
      {hasEntityDiff(diff.entity_diff) && (
        <section>
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
            Entity-level
          </h4>
          <div className="space-y-2">
            {diff.entity_diff.description && (
              <DiffBlock
                label="description"
                oldText={diff.entity_diff.description.old}
                newText={diff.entity_diff.description.new}
              />
            )}
            {diff.entity_diff.alias && (
              <DiffBlock
                label="alias"
                oldText={diff.entity_diff.alias.old}
                newText={diff.entity_diff.alias.new}
              />
            )}
            {diff.entity_diff.business_process && (
              <DiffBlock
                label="business_process"
                oldText={diff.entity_diff.business_process.old}
                newText={diff.entity_diff.business_process.new}
              />
            )}
          </div>
        </section>
      )}

      {/* Field-level diffs */}
      {diff.field_diffs.length > 0 && (
        <section>
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
            Fields ({diff.field_diffs.length} changed)
          </h4>
          <div className="space-y-3">
            {diff.field_diffs.map((fd) => (
              <div
                key={fd.field_name}
                className="border border-gray-200 rounded p-2 space-y-2"
              >
                <div className="text-xs font-mono text-gray-800">{fd.field_name}</div>
                {fd.description && (
                  <DiffBlock
                    label="description"
                    oldText={fd.description.old}
                    newText={fd.description.new}
                  />
                )}
                {fd.synonyms && (
                  <DiffBlock
                    label="synonyms"
                    oldText={renderSynonyms(fd.synonyms.old)}
                    newText={renderSynonyms(fd.synonyms.new)}
                  />
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Skipped fields */}
      {diff.fields_skipped_technical.length > 0 && (
        <details className="text-[11px] text-gray-500">
          <summary className="cursor-pointer hover:text-gray-700">
            Skipped technical fields ({diff.fields_skipped_technical.length})
          </summary>
          <div className="mt-1 font-mono px-2 text-gray-400 break-words">
            {diff.fields_skipped_technical.join(', ')}
          </div>
        </details>
      )}

      {totalChanges === 0 && (
        <div className="py-3 space-y-3">
          <p className="text-xs text-gray-500 italic text-center">
            The model returned no changes for the selected scope.
          </p>
          {diff.diagnostic && (
            <ZeroChangeDiagnostic diagnostic={diff.diagnostic} />
          )}
        </div>
      )}
    </div>
  )
}

function ZeroChangeDiagnostic({
  diagnostic,
}: {
  diagnostic: NonNullable<EnrichEntityResponse['diagnostic']>
}) {
  // Verdict picker — parse errors take priority because they explain why
  // we can't even compute a diff. Then cardinality-based heuristics for
  // the 0-changes path. Labels written to read as a sentence the admin can
  // act on, not jargon.
  let verdict: { label: string; tone: 'neutral' | 'warn' | 'bad' }
  if (diagnostic.parse_error) {
    verdict = {
      label:
        "The model's response wasn't valid JSON — usually because it ran out of output tokens mid-reply. Try selecting fewer fields and running again, or switch to a model with a larger output window.",
      tone: 'bad',
    }
  } else if (diagnostic.original_field_count === 0) {
    verdict = { label: 'Nothing to enrich — this entity has no fields in scope.', tone: 'neutral' }
  } else if (diagnostic.matched_field_count === diagnostic.original_field_count) {
    verdict = {
      label:
        "The model decided your existing descriptions were already good — it returned every field unchanged. If you think a field could still be improved, unselect the ones with strong descriptions and re-run; the model focuses better with a narrower scope.",
      tone: 'warn',
    }
  } else if (diagnostic.fields_only_in_enriched.length > 0) {
    verdict = {
      label:
        'The model invented or renamed field names that do not exist on the entity. We cannot apply those changes safely. Try running again — this usually self-corrects on retry.',
      tone: 'bad',
    }
  } else if (diagnostic.enriched_field_count < diagnostic.original_field_count) {
    verdict = {
      label:
        'The model returned fewer fields than the entity has, so its reply was likely truncated. Reduce the scope (fewer fields per run) and try again.',
      tone: 'bad',
    }
  } else {
    verdict = {
      label:
        "No obvious cause — the response is intact but produced no changes. Inspect the preview below; if it looks reasonable, the model just didn't see anything worth improving.",
      tone: 'neutral',
    }
  }

  const toneCls = {
    neutral: 'bg-gray-50 border-gray-200 text-gray-700',
    warn: 'bg-amber-50 border-amber-200 text-amber-800',
    bad: 'bg-red-50 border-red-200 text-red-800',
  }[verdict.tone]

  return (
    <div className={`text-[11px] rounded border px-3 py-2 space-y-1.5 ${toneCls}`}>
      <div className="font-semibold">Diagnostic</div>
      <div>{verdict.label}</div>

      {diagnostic.parse_error && (
        <pre className="text-[10px] font-mono whitespace-pre-wrap bg-white/60 p-1.5 rounded border border-current/20">
          {diagnostic.parse_error}
        </pre>
      )}

      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono">
        <span className="text-gray-500">original fields:</span>
        <span>{diagnostic.original_field_count}</span>
        {!diagnostic.parse_error && (
          <>
            <span className="text-gray-500">enriched fields:</span>
            <span>{diagnostic.enriched_field_count}</span>
            <span className="text-gray-500">matched by name:</span>
            <span>{diagnostic.matched_field_count}</span>
          </>
        )}
        <span className="text-gray-500">response size:</span>
        <span>{diagnostic.response_chars.toLocaleString()} chars</span>
      </div>
      {diagnostic.fields_only_in_enriched.length > 0 && (
        <div>
          <span className="text-gray-500">renamed / new in response:</span>{' '}
          <code className="font-mono">{diagnostic.fields_only_in_enriched.join(', ')}</code>
        </div>
      )}
      {!diagnostic.parse_error && diagnostic.fields_only_in_original.length > 0 && (
        <div>
          <span className="text-gray-500">missing from response:</span>{' '}
          <code className="font-mono">{diagnostic.fields_only_in_original.join(', ')}</code>
        </div>
      )}
      {diagnostic.response_preview && (
        <details>
          <summary className="cursor-pointer hover:underline">
            First chars of the raw response
          </summary>
          <pre className="mt-1 p-2 bg-white border border-gray-200 rounded font-mono text-[10px] whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
            {diagnostic.response_preview}
          </pre>
        </details>
      )}
      {diagnostic.response_tail && (
        <details>
          <summary className="cursor-pointer hover:underline">
            Last chars of the raw response (look here for truncation)
          </summary>
          <pre className="mt-1 p-2 bg-white border border-gray-200 rounded font-mono text-[10px] whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
            {diagnostic.response_tail}
          </pre>
        </details>
      )}
    </div>
  )
}

function DiffBlock({
  label,
  oldText,
  newText,
}: {
  label: string
  oldText: string
  newText: string
}) {
  return (
    <div className="text-[11px] grid grid-cols-[80px_1fr] gap-2">
      <span className="text-gray-500 font-mono">{label}</span>
      <div className="space-y-1">
        <div className="flex gap-1.5">
          <span className="text-gray-400 shrink-0">old</span>
          <span className="text-gray-700 line-through decoration-red-300/60">
            {oldText || <em className="text-gray-300">empty</em>}
          </span>
        </div>
        <div className="flex gap-1.5">
          <span className="text-emerald-700 shrink-0">new</span>
          <span className="text-gray-900 font-medium">{newText}</span>
        </div>
      </div>
    </div>
  )
}

function renderSynonyms(list: string[]): string {
  return list.length ? `[${list.join(', ')}]` : ''
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function hasEntityDiff(d: EnrichEntityResponse['entity_diff']): boolean {
  return Boolean(d.description || d.alias || d.business_process)
}

function countChanges(diff: EnrichEntityResponse): number {
  let n = 0
  if (diff.entity_diff.description) n++
  if (diff.entity_diff.alias) n++
  if (diff.entity_diff.business_process) n++
  for (const fd of diff.field_diffs) {
    if (fd.description) n++
    if (fd.synonyms) n++
  }
  return n
}

function hasAnyChange(diff: EnrichEntityResponse): boolean {
  return countChanges(diff) > 0
}

function buildUpdatePayload(
  diff: EnrichEntityResponse,
  authorEmail: string | undefined,
): YAMLUpdateRequest {
  // `source: 'ai_assist'` makes the git commit message reflect the provenance
  // ("ai-enrich(<id>): N fields — applied via AI Assist") so the history
  // tells you which changes came from the LLM vs the manual editor.
  const payload: YAMLUpdateRequest = { source: 'ai_assist' }
  if (authorEmail) payload.author_email = authorEmail

  if (diff.entity_diff.description) {
    payload.description = diff.entity_diff.description.new
  }
  if (diff.entity_diff.alias) {
    payload.alias = diff.entity_diff.alias.new
  }
  if (diff.field_diffs.length > 0) {
    payload.fields = diff.field_diffs.map((fd) => {
      const update: { name: string; description?: string; synonyms?: string[] } = {
        name: fd.field_name,
      }
      if (fd.description) update.description = fd.description.new
      if (fd.synonyms) update.synonyms = fd.synonyms.new
      return update
    })
  }
  return payload
}
