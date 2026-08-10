import { ChevronDown, ChevronRight, Sparkles } from 'lucide-react'
import { useState } from 'react'

import { useEditorStore } from '../../store/editorStore'
import { useGraphStore } from '../../store/graphStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useTranslation } from '../../hooks/useTranslation'
import type { SuggestedRelationship, VizRelationship, YAMLNode } from '../../api/types'
import { SuggestRelationshipDialog } from '../enrichment/SuggestRelationshipDialog'
import { JoinConditionEditor } from './JoinConditionEditor'
import { AGG_SAFETY, REL_TYPES } from '../../lib/semanticConstants'

interface RelationshipsEditorProps {
  relationships: VizRelationship[]
  onChange(relationships: VizRelationship[]): void
  /** The entity being edited — drives field pickers + auto-derive logic. */
  thisEntity: YAMLNode
}

// REL_TYPES / AGG_SAFETY come from lib/semanticConstants — do not redeclare them
// here. Both are now closed sets on the backend model, so a local copy that drifts
// would offer a value the API rejects.

/**
 * Cost rubric presets (Standards §7). Hides the magic numbers behind names
 * a non-engineer can pick. Custom slot lets advanced users still set any
 * number when an FK truly doesn't fit one of the buckets.
 */
const COST_PRESETS = [
  { key: 'direct', label: 'Direct FK', value: 1 },
  { key: 'indirect', label: 'Indirect', value: 1.5 },
  { key: 'cross_module', label: 'Cross-module', value: 2 },
  { key: 'heavy', label: 'Heavy / dedup', value: 3 },
] as const

/**
 * Default ``aggregation_safety`` derived from cardinality. Many-to-one and
 * one-to-one preserve grain on join → safe. Anything that fans out the
 * fact table needs deduplication.
 */
function deriveAggSafety(relType: string | null | undefined): typeof AGG_SAFETY[number] {
  switch (relType) {
    case 'many_to_one':
    case 'one_to_one':
      return 'safe'
    case 'one_to_many':
    case 'many_to_many':
      return 'requires_dedup'
    default:
      return 'safe'
  }
}

function blank(): VizRelationship {
  return {
    target_entity: '',
    relationship_type: 'many_to_one',
    join_condition: null,
    semantic_label: null,
    traversal_cost: 1,
    aggregation_safety: 'safe',
    cross_module: false,
    description: null,
  }
}

export function RelationshipsEditor({
  relationships,
  onChange,
  thisEntity,
}: RelationshipsEditorProps) {
  const { t } = useTranslation()
  const rawNodes = useGraphStore((s) => s.rawNodes)

  // Catalogue of Silver/Gold entities the admin can point to. Indexed by id
  // so the card can resolve the target's fields for the column pickers.
  const targetCatalogue = rawNodes.filter((n) => n.layer === 'silver' || n.layer === 'gold')
  const byId = new Map(targetCatalogue.map((n) => [n.id, n]))

  function update(i: number, patch: Partial<VizRelationship>) {
    onChange(relationships.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }
  function remove(i: number) {
    onChange(relationships.filter((_, idx) => idx !== i))
  }
  function add() {
    onChange([...relationships, blank()])
  }

  return (
    <div className="flex flex-col gap-2">
      <datalist id="rel-target-ids">
        {targetCatalogue.map((n) => (
          <option key={n.id} value={n.id} />
        ))}
      </datalist>

      {relationships.map((rel, i) => (
        <RelationshipCard
          key={i}
          rel={rel}
          thisEntity={thisEntity}
          targetEntity={byId.get(rel.target_entity ?? '') ?? null}
          targetCatalogue={targetCatalogue}
          onUpdate={(patch) => update(i, patch)}
          onRemove={() => remove(i)}
        />
      ))}

      <button
        onClick={add}
        className="self-start text-xs text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2 py-1 hover:bg-blue-50 transition-colors"
      >
        {t('re_add_relationship')}
      </button>
    </div>
  )
}

// ── Per-relationship card ──────────────────────────────────────────────────

interface CardProps {
  rel: VizRelationship
  thisEntity: YAMLNode
  targetEntity: YAMLNode | null
  targetCatalogue: YAMLNode[]
  onUpdate(patch: Partial<VizRelationship>): void
  onRemove(): void
}

function RelationshipCard({
  rel,
  thisEntity,
  targetEntity,
  targetCatalogue,
  onUpdate,
  onRemove,
}: CardProps) {
  const { t } = useTranslation()
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [suggestOpen, setSuggestOpen] = useState(false)
  const addCommitNotes = useEditorStore((s) => s.addCommitNotes)
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId)

  function applySuggestion(s: SuggestedRelationship, caveats: string[]) {
    // Pegamos la suggestion al editBuffer (vía onUpdate) y los caveats al
    // store del editor para que Save los meta en el commit message. Cero
    // pollution del YAML.
    onUpdate({
      target_entity: s.target_entity,
      relationship_type: s.relationship_type,
      join_condition: s.join_condition,
      semantic_label: s.semantic_label,
      traversal_cost: s.traversal_cost,
      aggregation_safety: s.aggregation_safety,
      cross_module: s.cross_module,
      description: s.description,
    })
    if (caveats.length > 0) {
      addCommitNotes(
        caveats.map((c) => `${rel.target_entity || s.target_entity}: ${c}`),
      )
    }
  }

  function switchToManualAfterNoMatch() {
    // The model couldn't suggest — keep the target the admin picked, clear
    // the join_condition so they see an empty Expert-mode editor instead of
    // a half-filled one.
    onUpdate({ join_condition: null })
  }

  // Catch a target_entity that's been deleted from the workspace — flag it
  // visually so the admin can't silently ship a dead lineage edge.
  const targetExists = !rel.target_entity || targetCatalogue.some((n) => n.id === rel.target_entity)

  // Cost is stored as a number but selected as a preset. Match the current
  // value back to a preset when possible; otherwise show "Custom".
  const presetMatch = COST_PRESETS.find((p) => p.value === (rel.traversal_cost ?? 1))
  const costPresetKey = presetMatch ? presetMatch.key : 'custom'

  function changeRelType(t: string) {
    // Auto-update aggregation_safety alongside the type — they're tightly
    // correlated and the admin almost always wants the derived value. They
    // can still override it in Advanced afterwards.
    onUpdate({
      relationship_type: t,
      aggregation_safety: deriveAggSafety(t),
    })
  }

  function changeTarget(targetId: string) {
    // Auto-detect cross_module by comparing modules. If we can't tell
    // (target unresolved or one of the modules empty), leave whatever the
    // user previously set.
    const target = targetCatalogue.find((n) => n.id === targetId)
    const thisModule = (thisEntity.module ?? '').trim().toLowerCase()
    const targetModule = (target?.module ?? '').trim().toLowerCase()
    const crossModuleAuto =
      thisModule && targetModule ? thisModule !== targetModule : (rel.cross_module ?? false)

    onUpdate({
      target_entity: targetId,
      cross_module: crossModuleAuto,
    })
  }

  function changeCostPreset(key: string) {
    if (key === 'custom') return // Keep current value, let the number input below take over.
    const p = COST_PRESETS.find((x) => x.key === key)
    if (p) onUpdate({ traversal_cost: p.value })
  }

  return (
    <div className="p-2 bg-gray-50 border border-gray-200 rounded flex flex-col gap-1.5">
      {/* Header — target picker + delete */}
      <div className="flex items-center gap-1.5">
        <input
          list="rel-target-ids"
          type="text"
          value={rel.target_entity}
          onChange={(e) => changeTarget(e.target.value)}
          placeholder="target entity id (silver_/gold_…)"
          title="The entity this one joins to"
          className={`flex-1 min-w-0 text-xs border rounded px-1.5 py-0.5 font-mono bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${
            targetExists ? 'border-gray-300' : 'border-red-400 bg-red-50'
          }`}
        />
        {!targetExists && (
          <span
            className="text-[10px] text-red-700 bg-red-100 px-1.5 py-0.5 rounded"
            title="This target entity is not in the workspace catalogue. Either fix the id or delete this relationship."
          >
            {t('re_not_found')}
          </span>
        )}
        {/* Suggest button — only meaningful once the admin picked a real target.
            Cleaner to disable than hide so the affordance stays in the same
            place when targets come/go. */}
        <button
          type="button"
          onClick={() => setSuggestOpen(true)}
          disabled={!rel.target_entity || !targetExists || !targetEntity}
          className="inline-flex items-center gap-1 text-[11px] font-medium rounded px-2 py-0.5 border border-violet-300 bg-white text-violet-700 hover:bg-violet-50 disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          title={
            !rel.target_entity || !targetExists
              ? 'Pick a target entity first — the AI needs to know which entity to suggest the join against.'
              : 'Ask the AI to fill in join + cardinality + cost. Caveats are kept in the git commit, not in the YAML.'
          }
        >
          <Sparkles className="h-3 w-3" />
          Suggest
        </button>
        <button
          onClick={onRemove}
          className="text-gray-400 hover:text-red-500 text-base leading-none px-1 shrink-0"
          aria-label="Remove relationship"
          title="Remove this relationship"
        >
          ×
        </button>
      </div>

      {/* Always-visible essentials: type + label */}
      <div className="grid grid-cols-2 gap-1.5">
        <select
          value={rel.relationship_type ?? 'many_to_one'}
          onChange={(e) => changeRelType(e.target.value)}
          title="Cardinality — drives both path planning AND aggregation safety."
          className="text-xs border border-gray-300 rounded px-1 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
        >
          {REL_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={rel.semantic_label ?? ''}
          onChange={(e) => onUpdate({ semantic_label: e.target.value || null })}
          placeholder="semantic label (e.g. sold_to)"
          title="Short business verb shown on the graph edge"
          className="text-xs border border-gray-300 rounded px-1.5 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>

      {/* JOIN ON — column picker pairs (N pairs supported for composite keys) */}
      <div className="pt-1">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-1">
          {t('re_join_on')}
        </div>
        <JoinConditionEditor
          value={rel.join_condition ?? ''}
          onChange={(v) => onUpdate({ join_condition: v || null })}
          thisEntity={{
            id: thisEntity.id,
            db_table_name: thisEntity.db_table_name,
            fields: thisEntity.fields,
          }}
          targetEntity={targetEntity}
        />
      </div>

      {/* Advanced — collapsed by default to keep the card scannable. */}
      <button
        type="button"
        onClick={() => setAdvancedOpen((v) => !v)}
        className="self-start text-[11px] text-gray-500 hover:text-gray-700 inline-flex items-center gap-0.5 mt-0.5"
      >
        {advancedOpen ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        {t('re_advanced')}
      </button>

      {advancedOpen && (
        <div className="grid grid-cols-2 gap-1.5 pt-1 border-t border-gray-200">
          {/* Cost preset + (optional) custom number */}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-500">{t('re_traversal_cost')}</label>
            <div className="flex gap-1.5">
              <select
                value={costPresetKey}
                onChange={(e) => changeCostPreset(e.target.value)}
                title="Dijkstra weight — see cost rubric (standards §7)."
                className="flex-1 min-w-0 text-xs border border-gray-300 rounded px-1 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                {COST_PRESETS.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label} ({p.value})
                  </option>
                ))}
                <option value="custom">{t('re_custom')}</option>
              </select>
              {costPresetKey === 'custom' && (
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={rel.traversal_cost ?? 1}
                  onChange={(e) => onUpdate({ traversal_cost: Number(e.target.value) })}
                  className="w-20 text-xs border border-gray-300 rounded px-1.5 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              )}
            </div>
          </div>

          {/* Aggregation safety (auto-derived; admin can still override). */}
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-500">{t('re_agg_safety')}</label>
            <select
              value={rel.aggregation_safety ?? 'safe'}
              onChange={(e) => onUpdate({ aggregation_safety: e.target.value })}
              title="safe · requires_dedup (fan-out) · unsafe (rejected). Auto-derived from relationship_type — override if the FK pattern justifies it."
              className="text-xs border border-gray-300 rounded px-1 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              {AGG_SAFETY.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>

          {/* Cross-module toggle (auto-detected from module diff). */}
          <label className="flex items-center gap-1.5 text-[11px] text-gray-600 px-1 col-span-2">
            <input
              type="checkbox"
              checked={!!rel.cross_module}
              onChange={(e) => onUpdate({ cross_module: e.target.checked })}
              className="rounded"
            />
            {t('re_cross_module')}{' '}
            <span className="text-[10px] text-gray-400">
              {t('re_cross_module_auto')}
            </span>
          </label>

          {/* Description — kept in Advanced because it's free-text + the
              graph edge label already shows semantic_label. */}
          <div className="col-span-2 flex flex-col gap-1">
            <label className="text-[10px] text-gray-500">{t('re_description')}</label>
            <input
              type="text"
              value={rel.description ?? ''}
              onChange={(e) => onUpdate({ description: e.target.value || null })}
              placeholder="business meaning + traversal caveat"
              className="text-xs border border-gray-300 rounded px-1.5 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
          </div>
        </div>
      )}

      {suggestOpen && rel.target_entity && targetEntity && (
        <SuggestRelationshipDialog
          open
          onClose={() => setSuggestOpen(false)}
          sourceEntityId={thisEntity.id}
          targetEntityId={rel.target_entity}
          workspaceId={activeWorkspaceId ?? null}
          onApply={applySuggestion}
          onSwitchToManual={switchToManualAfterNoMatch}
        />
      )}
    </div>
  )
}
