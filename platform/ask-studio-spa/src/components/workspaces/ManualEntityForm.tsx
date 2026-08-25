/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { HelpCircle, Loader2, Plus, Sparkles, Trash2 } from 'lucide-react'
import { type Dispatch, type ReactNode, type SetStateAction, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { stringify as stringifyYaml } from 'yaml'

import {
  getCatalog,
  getIngestConfig,
  getOrganization,
  getYaml,
  importYamlToWorkspace,
  previewEntityEnrichmentDraft,
  previewFieldEnrichmentDraft,
  suggestRelationshipCompleteDraft,
} from '@/api/client'
import type { LightweightEntity, VizField, YAMLNode } from '@/api/types'
import { Button } from '@/components/ui/button'
import { CanonicalTypeSelect } from '@/components/editor/CanonicalTypeEditor'
import { AdvancedToggle, FieldAdvanced } from '@/components/editor/FieldAdvanced'
import { JoinConditionEditor } from '@/components/editor/JoinConditionEditor'
import { deriveFieldRoleFromType, toCanonicalType } from '@/lib/canonicalType'
import {
  AGG_SAFETY,
  CLASSIFICATIONS,
  COST_PRESETS,
  ENTITY_ROLES,
  FIELD_ROLES,
  JOIN_TYPES,
  REL_TYPES,
  deriveAggSafety,
} from '@/lib/semanticConstants'
import { useTranslation } from '@/hooks/useTranslation'

/**
 * Manual authoring form (entity-creation redesign). You provide the semantic
 * core; the EntityDeriver fills the scaffolding (previewed live on the right);
 * AI drafts descriptions from the draft as a recipe. Multi-table Silvers: pick
 * the bronze tables — fields + join rows auto-fill, only the join condition is
 * manual. join_graph is lineage documentation, not a runtime join (the agent
 * queries the single db_table_name). See ITERATION_ENTITY_CREATION_REDESIGN.md.
 */

type Layer = 'bronze' | 'silver' | 'gold'

interface BronzeFieldRow {
  name: string
  type: string
  alias: string
  keyField: boolean
  description: string
}

interface SgFieldRow {
  name: string
  source: string
  type: string
  fieldRole: string // '' = auto (derived from type). 'identifier' marks a key.
  aggregationBehavior: string
  synonyms: string[]
  description: string
  sourceTable: string // bronze name this field came from ('' = manual)
}

interface JoinRow {
  left: string
  right: string
  joinType: string
  condition: string
  sequence: number
}

interface RelRow {
  targetEntity: string
  relationshipType: string
  joinCondition: string
  semanticLabel: string
  traversalCost: number
  aggregationSafety: string
  crossModule: boolean
  description: string
}

interface Props {
  onCreated: () => void
  onClose: () => void
}

const MODULES = ['sd', 'mm', 'pp', 'fi', 'co'] as const

function slug(s: string): string {
  return s.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}

export function ManualEntityForm({ onCreated, onClose }: Props) {
  const { t } = useTranslation()
  const [layer, setLayer] = useState<Layer>('silver')
  const [busy, setBusy] = useState(false)

  // Common
  const [sourceSystem, setSourceSystem] = useState('s4h')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  // Bronze
  const [alias, setAlias] = useState('')
  const [bronzeFields, setBronzeFields] = useState<BronzeFieldRow[]>([
    { name: '', type: 'STRING(10)', alias: '', keyField: true, description: '' },
  ])

  // Silver / Gold
  const [modules, setModules] = useState<string[]>(['sd'])
  const [dbTableName, setDbTableName] = useState('')
  // A Silver that IS one table has no bronze beneath it — the shape a DDL import
  // already produces from a bare CREATE TABLE. `composed_of` stays required (the
  // workspace scope resolver and the publish cascade both read it), so this fills
  // it with the entity's own physical table rather than relaxing the contract.
  const [isFlat, setIsFlat] = useState(false)
  const [classification, setClassification] = useState('T')
  // Gold authors entity_role directly (see derivedEntityRole).
  const [goldEntityRole, setGoldEntityRole] = useState('fact')
  const [composed, setComposed] = useState<string[]>([]) // bronze ids, [0]=root
  const [joins, setJoins] = useState<JoinRow[]>([])
  const [sgFields, setSgFields] = useState<SgFieldRow[]>([])
  const [rels, setRels] = useState<RelRow[]>([])

  // Deployment column-naming mode (technical | alias) — decides how imported
  // bronze fields are named ('vbeln_vbak' vs 'documento_ventas_vbak').
  const [columnNaming, setColumnNaming] = useState<'technical' | 'alias'>('technical')

  // Catalog + caches
  const [catalog, setCatalog] = useState<LightweightEntity[]>([])
  const [bronzeCache, setBronzeCache] = useState<Record<string, YAMLNode>>({})
  const [targetCache, setTargetCache] = useState<Record<string, YAMLNode>>({})
  const [pickBronze, setPickBronze] = useState('')
  const [pickTarget, setPickTarget] = useState('')
  const [aiBusy, setAiBusy] = useState<string | null>(null)

  const isBronze = layer === 'bronze'

  // ── Load org default source_system + catalog on mount ─────────────────────
  useEffect(() => {
    void (async () => {
      try {
        const org = await getOrganization()
        const ss = (org.source_system || org.sap_version || '').trim()
        if (ss) {
          // The Organization source_system is a free label ("SAP S/4HANA 2023");
          // the entity source_system is the short key. Use the catalog's existing
          // bronze ids to keep the default sensible; else leave 's4h'.
          const firstTok = ss.toLowerCase().split(/[\s_]/)[0]
          if (firstTok) setSourceSystem(firstTok === 'sap' ? 's4h' : firstTok)
        }
      } catch {
        /* non-fatal — keep default */
      }
      try {
        setCatalog(await getCatalog())
      } catch {
        /* non-fatal */
      }
      try {
        setColumnNaming((await getIngestConfig()).column_naming)
      } catch {
        /* non-fatal — keep 'technical', the backend default */
      }
    })()
  }, [])

  // ── Derived id ────────────────────────────────────────────────────────────
  const entityId = useMemo(() => {
    const ss = slug(sourceSystem)
    const ent = slug(name)
    if (isBronze) {
      const a = slug(alias) || ent
      return ent ? `bronze_${ss}_${ent}_${a}` : ''
    }
    if (!ent) return ''
    if (layer === 'gold') return `gold_${ss}_${ent}`
    return modules[0] ? `silver_${ss}_${slug(modules[0])}_${ent}` : ''
  }, [isBronze, layer, name, alias, sourceSystem, modules])

  // Silver only — mirrors EntityDeriver.entity_role (standards §5.1). GOLD authors
  // the role instead: the derivation keys off SAP artefacts a Gold does not have,
  // so the backend no longer recomputes it there and `fact` is the default.
  const derivedEntityRole = useMemo(() => {
    if (layer === 'gold') return goldEntityRole
    const c = classification.toUpperCase()
    if (c === 'C') return 'reference'
    if (c === 'M') return 'dimension'
    if (c === 'T') {
      const hasMeasure = sgFields.some((f) => (f.fieldRole || deriveFieldRoleFromType(f.type)) === 'measure')
      return name.toLowerCase().includes('item') || hasMeasure ? 'fact' : 'dimension'
    }
    return 'dimension'
  }, [layer, goldEntityRole, classification, name, sgFields])

  // entity_grain = the fields whose role is identifier (keys). There is no
  // separate key flag on Silver/Gold — role is the single source of truth.
  const grainKeys = useMemo(
    () =>
      sgFields
        .filter((f) => (f.fieldRole || deriveFieldRoleFromType(f.type)) === 'identifier')
        .map((f) => f.name)
        .filter(Boolean),
    [sgFields],
  )

  const businessGrainEff = name ? `${slug(name)}_item` : ''

  // The in-progress draft as a thisEntity for the structured JoinConditionEditor
  // (same component the global Edit uses) — exposes the draft's own fields as the
  // LEFT-side picker so relationship join conditions get field pickers, not raw text.
  const draftFields: VizField[] = useMemo(
    () =>
      sgFields
        .filter((f) => f.name.trim())
        .map((f) => {
          const role = f.fieldRole || deriveFieldRoleFromType(f.type)
          return {
            name: f.name.trim(),
            type: f.type || null,
            alias: null,
            key_field: role === 'identifier',
            description: f.description || null,
            source: f.source || null,
            field_role: role,
            aggregation_behavior: null,
            synonyms: [],
            normalization_flag: null,
          }
        }),
    [sgFields],
  )
  const bronzeKeys = bronzeFields.filter((f) => f.keyField && f.name.trim()).map((f) => f.name.trim())
  const recipeReady = !!slug(name) && !!sourceSystem && (isBronze ? bronzeFields : sgFields).some((f) => f.name.trim())

  // ── Bronze picker ───────────────────────────────────────────────────────────
  const bronzeOptions = catalog.filter((e) => e.layer === 'bronze' && !composed.includes(e.id))
  const targetOptions = catalog.filter(
    (e) => (e.layer === 'silver' || e.layer === 'gold') && e.id !== entityId && !rels.some((r) => r.targetEntity === e.id),
  )

  function tableNameOf(id: string): string {
    const node = bronzeCache[id]
    if (node?.name) return node.name.toUpperCase()
    const fromCat = catalog.find((e) => e.id === id)?.name
    return (fromCat || id).toUpperCase()
  }

  function keyFieldsOf(table: string): string[] {
    const node = Object.values(bronzeCache).find((n) => (n.name || '').toUpperCase() === table)
    if (!node) return []
    return node.fields.filter((f) => f.key_field).map((f) => (f.name || '').toUpperCase())
  }

  function guessCondition(left: string, right: string): string {
    const lk = keyFieldsOf(left)
    const rk = keyFieldsOf(right)
    const shared = lk.find((k) => rk.includes(k))
    return shared ? `${left}.${shared} = ${right}.${shared}` : ''
  }

  async function addBronze() {
    const bid = pickBronze
    if (!bid || composed.includes(bid)) return
    let node = bronzeCache[bid]
    if (!node) {
      try {
        node = await getYaml(bid)
        setBronzeCache((c) => ({ ...c, [bid]: node }))
      } catch {
        toast.error(`Could not load ${bid}`)
        return
      }
    }
    const table = (node.name || bid).toUpperCase()
    // Auto-import this bronze's fields. The published name follows the
    // deployment column-naming mode: 'alias' prefixes with the persisted
    // bronze alias (already sanitized + deduped server-side), 'technical'
    // with the SAP field code — same rule the SAP JSON parser applies.
    const imported: SgFieldRow[] = node.fields.map((f) => {
      const col = (f.name || '').toUpperCase()
      const prefix = columnNaming === 'alias' ? f.alias || f.name || '' : f.name || ''
      return {
        name: `${prefix.toLowerCase()}_${table.toLowerCase()}`,
        source: `${table}.${col}`,
        type: toCanonicalType(f.type || 'STRING'),
        // A bronze key becomes a Silver identifier (the only key signal on s/g).
        fieldRole: f.key_field ? 'identifier' : '',
        aggregationBehavior: 'none',
        synonyms: [],
        description: f.description || '',
        sourceTable: table,
      }
    })
    const isRoot = composed.length === 0
    setComposed((c) => [...c, bid])
    setSgFields((rows) => [...rows, ...imported])
    if (!isRoot) {
      const root = tableNameOf(composed[0])
      setJoins((js) => [
        ...js,
        { left: root, right: table, joinType: 'INNER', condition: guessCondition(root, table), sequence: js.length + 2 },
      ])
    }
    setPickBronze('')
  }

  function removeBronze(idx: number) {
    const bid = composed[idx]
    const table = tableNameOf(bid)
    setComposed((c) => c.filter((_, i) => i !== idx))
    setSgFields((rows) => rows.filter((f) => f.sourceTable !== table))
    setJoins((js) => js.filter((j) => j.right !== table).map((j, i) => ({ ...j, sequence: i + 2 })))
  }

  // ── Relationships ───────────────────────────────────────────────────────────
  async function addRel() {
    if (!pickTarget) return
    const tid = pickTarget
    setRels((rs) => [
      ...rs,
      {
        targetEntity: tid,
        relationshipType: 'many_to_one',
        joinCondition: '',
        semanticLabel: '',
        traversalCost: 1,
        aggregationSafety: 'safe',
        crossModule: false,
        description: '',
      },
    ])
    setPickTarget('')
    // Load the target's fields so the JoinConditionEditor can offer a RIGHT-side
    // field picker (parity with the global Edit).
    if (!targetCache[tid]) {
      try {
        const node = await getYaml(tid)
        setTargetCache((c) => ({ ...c, [tid]: node }))
      } catch {
        /* picker degrades to free-text; non-fatal */
      }
    }
  }

  async function suggestRel(i: number) {
    const r = rels[i]
    if (!r.targetEntity) return
    setAiBusy(`rel:${i}`)
    try {
      const resp = await suggestRelationshipCompleteDraft({
        source_raw_yaml: assembleNode(),
        target_entity_id: r.targetEntity,
      })
      const s = resp.relationship
      if (!s) {
        toast.message(resp.no_match_reason || 'No relationship suggested')
        return
      }
      setRels((rows) =>
        rows.map((row, idx) =>
          idx === i
            ? {
                ...row,
                relationshipType: s.relationship_type || row.relationshipType,
                joinCondition: s.join_condition || row.joinCondition,
                semanticLabel: s.semantic_label || row.semanticLabel,
                traversalCost: s.traversal_cost ?? row.traversalCost,
                aggregationSafety: s.aggregation_safety || row.aggregationSafety,
                crossModule: s.cross_module ?? row.crossModule,
                description: s.description || row.description,
              }
            : row,
        ),
      )
      if (resp.caveats?.length) toast.message(`Applied with caveats: ${resp.caveats.join('; ')}`)
    } catch (e: unknown) {
      toast.error(errMsg(e, 'Suggest failed'))
    } finally {
      setAiBusy(null)
    }
  }

  // ── AI descriptions ─────────────────────────────────────────────────────────
  async function aiEntityDescription() {
    setAiBusy('entity-desc')
    try {
      const resp = await previewEntityEnrichmentDraft({
        raw_yaml: assembleNode(),
        scope: { entity_level: true, field_names: [] },
      })
      const next = resp.entity_diff?.description?.new
      if (next) setDescription(next)
      else toast.message('No description suggested')
    } catch (e: unknown) {
      toast.error(errMsg(e, 'AI assist failed'))
    } finally {
      setAiBusy(null)
    }
  }

  async function aiFieldDescription(i: number) {
    const f = sgFields[i]
    if (!f.name.trim()) return
    setAiBusy(`field:${i}`)
    try {
      const resp = await previewFieldEnrichmentDraft({ raw_yaml: assembleNode(), field_name: f.name })
      const next = resp.diff?.description?.new
      if (next) setSgFields((rows) => rows.map((row, idx) => (idx === i ? { ...row, description: next } : row)))
      else toast.message('No description suggested')
    } catch (e: unknown) {
      toast.error(errMsg(e, 'AI assist failed'))
    } finally {
      setAiBusy(null)
    }
  }

  async function aiAllDescriptions() {
    const emptyFieldNames = sgFields.filter((f) => f.name.trim() && !f.description.trim()).map((f) => f.name)
    setAiBusy('bulk-desc')
    try {
      const resp = await previewEntityEnrichmentDraft({
        raw_yaml: assembleNode(),
        scope: { entity_level: true, field_names: emptyFieldNames },
      })
      if (!description.trim() && resp.entity_diff?.description?.new) setDescription(resp.entity_diff.description.new)
      const byName = new Map((resp.field_diffs || []).map((d) => [d.field_name, d.description?.new]))
      setSgFields((rows) =>
        rows.map((row) => {
          const next = byName.get(row.name)
          return !row.description.trim() && next ? { ...row, description: next } : row
        }),
      )
      toast.success('Descriptions drafted (empty ones only)')
    } catch (e: unknown) {
      toast.error(errMsg(e, 'AI assist failed'))
    } finally {
      setAiBusy(null)
    }
  }

  // ── Assemble + validate + save ───────────────────────────────────────────────
  function assembleNode(): Record<string, unknown> {
    if (isBronze) {
      const rows = bronzeFields.filter((f) => f.name.trim())
      return {
        id: entityId,
        layer: 'bronze',
        version: '1',
        source_system: sourceSystem.trim(),
        source_system_id: 100,
        name: name.trim(),
        alias: slug(alias) || slug(name),
        description,
        primary_key: rows.filter((f) => f.keyField).map((f) => f.name.trim()),
        fields: Object.fromEntries(
          rows.map((f) => [
            f.name.trim(),
            {
              type: toCanonicalType(f.type),
              alias: f.alias.trim() || f.name.trim().toLowerCase(),
              key_field: f.keyField,
              description: f.description,
            },
          ]),
        ),
      }
    }

    const rows = sgFields.filter((f) => f.name.trim())
    const node: Record<string, unknown> = {
      id: entityId,
      layer,
      version: '1',
      source_system: sourceSystem.trim(),
      source_system_no: 100,
      // business_process is NOT derived from the module: they are two different
      // axes (standards §4.1). It is left empty so the enrichment scope flags it,
      // rather than silently seeding a module code as a business process.
      business_process: '',
      module: modules.length > 1 ? modules : modules[0] || '',
      name: slug(name),
      // Gold carries no Data-Modeler classification and drives nothing with it.
      ...(layer === 'gold' ? {} : { classification }),
      description,
      entity_role: derivedEntityRole,
      db_table_name: dbTableName.trim() || entityId,
      grain: { entity_grain: grainKeys, business_grain: businessGrainEff },
      fields: rows.map((f) => {
        const role = f.fieldRole || deriveFieldRoleFromType(f.type)
        // `source` = the author/picker-provided bronze lineage. Emitted only when
        // there IS one, so a Gold (and a flat Silver) simply omits the key.
        //
        // Gold used to be auto-filled with {db_table_name}.{name} — a self-reference
        // that states nothing AND is read as a real source table by the measure
        // fan-out derivation: with every field pointing at the Gold's own table, no
        // grain member came out functionally determined, so every uncurated Gold
        // measure was stamped `additivity: non_additive` + `aggregation_behavior:
        // none` ("never aggregate this"). The whole Gold plane went unsummable.
        const source = f.source.trim()
        const obj: Record<string, unknown> = {
          name: f.name.trim(),
          ...(source ? { source } : {}),
          field_role: role,
          type: toCanonicalType(f.type),
          description: f.description,
        }
        // 'none' is this form's UI default for every imported bronze field (see
        // the importer above), NOT a curator's "never sum this" — so stripping it
        // is correct here, unlike on the edit path where an explicit `none` is a
        // persisted decision. Non-additivity is declared after creation, in the
        // Edit panel, where the grain is settled enough to validate
        // `non_additive_over` against it (REQ_ADDITIVITY_CONTRACT.md).
        if (role === 'measure' && f.aggregationBehavior !== 'none') obj.aggregation_behavior = f.aggregationBehavior
        if (f.synonyms && f.synonyms.length) obj.synonyms = f.synonyms
        return obj
      }),
      relationships: rels
        .filter((r) => r.targetEntity.trim())
        .map((r) => ({
          target_entity: r.targetEntity.trim(),
          relationship_type: r.relationshipType,
          join_condition: r.joinCondition.trim(),
          semantic_label: r.semanticLabel.trim() || null,
          traversal_cost: r.traversalCost,
          aggregation_safety: r.aggregationSafety,
          cross_module: r.crossModule,
          description: r.description || null,
        })),
    }
    // Silver carries composed_of + join_graph (lineage); Gold omits both.
    if (layer === 'silver' && isFlat) {
      // One table, no joins — same shape the DDL import writes for a bare
      // CREATE TABLE, so every consumer of composed_of keeps working unchanged.
      node.composed_of = [dbTableName.trim() || entityId]
    } else if (layer === 'silver') {
      node.composed_of = composed
      node.join_graph = joins.map((j) => ({
        left_table: j.left,
        right_table: j.right,
        join_type: j.joinType,
        condition: j.condition.trim(),
        sequence: j.sequence,
      }))
    }
    return node
  }

  function validate(): string | null {
    if (!name.trim()) return 'Name is required'
    if (!entityId) return isBronze ? 'Name (and alias) are required' : layer === 'silver' ? 'Name + module are required' : 'Name is required'
    if (isBronze) {
      const rows = bronzeFields.filter((f) => f.name.trim())
      if (rows.length === 0) return 'Add at least one field'
      if (!rows.some((f) => f.keyField)) return 'Mark at least one field as a key'
      return null
    }
    if (modules.length === 0) return 'Pick at least one module'
    if (layer === 'silver' && !isFlat && composed.length === 0) return 'Pick at least one bronze table (composed_of)'
    if (layer === 'silver' && !dbTableName.trim() && !entityId) return 'db_table_name is required'
    const rows = sgFields.filter((f) => f.name.trim())
    if (rows.length === 0) return 'Add at least one field'
    // Silver fields must declare their bronze lineage (source). Gold auto-fills it.
    if (layer === 'silver')
      for (const f of rows) if (!f.source.trim()) return `Field "${f.name}" needs a source`
    if (!grainKeys.length) return 'Set at least one field role = identifier (defines the grain)'
    for (const j of joins) if (!j.condition.trim()) return `Join ${j.left}→${j.right} needs a condition`
    for (const r of rels) if (r.targetEntity.trim() && !r.joinCondition.trim()) return `Relationship to "${r.targetEntity}" needs a join condition`
    return null
  }

  async function handleSave() {
    const err = validate()
    if (err) {
      toast.error(err)
      return
    }
    setBusy(true)
    try {
      const yaml = stringifyYaml(assembleNode(), { lineWidth: 0 })
      const r = await importYamlToWorkspace(yaml, false)
      toast.success(`Created ${r.entity_id} (${r.layer}) — In Review`)
      onCreated()
      onClose()
    } catch (e: unknown) {
      toast.error(errMsg(e, 'Import failed'))
    } finally {
      setBusy(false)
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
      {/* Layer */}
      <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
        {(['bronze', 'silver', 'gold'] as Layer[]).map((l) => (
          <button
            key={l}
            onClick={() => setLayer(l)}
            className={`px-4 py-1.5 text-sm font-medium capitalize ${layer === l ? 'bg-blue-600 text-white' : 'bg-white text-gray-500'} ${l !== 'bronze' ? 'border-l border-gray-200' : ''}`}
          >
            {l}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* LEFT: semantic core */}
        <Section title={t('mef_section_you_provide')} hint="The semantic core — everything else is derived.">
          <div className="grid grid-cols-2 gap-2">
            <Labeled label={t('mef_source_label')} hint={t('mef_source_hint')}>
              <input value={sourceSystem} onChange={(e) => setSourceSystem(e.target.value)} className={inputCls} />
            </Labeled>
            <Labeled label={t('mef_name_label')}>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder={isBronze ? 'VBAK' : 'Sales Order'} className={inputCls} />
            </Labeled>
          </div>

          {!isBronze && (
            <div className="grid grid-cols-2 gap-2 mt-2">
              <Labeled label={t('mef_modules_label')} hint={t('mef_modules_hint')}>
                <div className="flex flex-wrap gap-1">
                  {MODULES.map((m) => (
                    <button
                      key={m}
                      onClick={() => setModules((ms) => (ms.includes(m) ? ms.filter((x) => x !== m) : [...ms, m]))}
                      className={`rounded-full px-2.5 py-0.5 text-xs border ${modules.includes(m) ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-500 border-gray-300'}`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </Labeled>
              {layer === 'gold' ? (
                <Labeled label={t('mef_entity_role_label')} hint={t('mef_entity_role_hint')}>
                  <select value={goldEntityRole} onChange={(e) => setGoldEntityRole(e.target.value)} className={inputCls}>
                    {ENTITY_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </Labeled>
              ) : (
                <Labeled label={t('mef_classification_label')} hint={t('mef_classification_hint')}>
                  <select value={classification} onChange={(e) => setClassification(e.target.value)} className={inputCls}>
                    {CLASSIFICATIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                </Labeled>
              )}
            </div>
          )}

          {isBronze && (
            <Labeled label={t('mef_alias_label')} hint={t('mef_alias_hint')} className="mt-2">
              <input value={alias} onChange={(e) => setAlias(e.target.value)} className={inputCls} />
            </Labeled>
          )}

          {!isBronze && (
            <Labeled label={t('mef_db_table_label')} hint={t('mef_db_table_hint')} className="mt-2">
              <input value={dbTableName} onChange={(e) => setDbTableName(e.target.value)} placeholder={entityId} className={`${inputCls} font-mono`} />
            </Labeled>
          )}

          <Labeled label={t('mef_description_label')} hint={t('mef_description_hint')} className="mt-2">
            <div className="relative">
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className={`${inputCls} resize-y pr-16`} placeholder="What this entity is, its grain, when to use it…" />
              <AiBtn onClick={() => void aiEntityDescription()} disabled={!recipeReady || aiBusy !== null} busy={aiBusy === 'entity-desc'} className="absolute right-1.5 bottom-1.5" />
            </div>
          </Labeled>
        </Section>

        {/* RIGHT: derived preview */}
        <Section title={t('mef_section_auto_derived')} hint="Preview — the deriver fills these on save; override on the left.">
          <div className="rounded-lg border border-amber-200 bg-amber-50/40 p-3 text-xs space-y-1.5">
            <DRow k="id" v={entityId} />
            {!isBronze && <DRow k="internal_id" v={entityId} />}
            {!isBronze && <DRow k="entity_role" v={derivedEntityRole} />}
            {!isBronze && <DRow k="grain.entity_grain" v={grainKeys.length ? `[${grainKeys.join(', ')}]` : '(set a field role = identifier)'} />}
            {!isBronze && <DRow k="grain.business_grain" v={businessGrainEff} />}
            {isBronze && <DRow k="primary_key" v={bronzeKeys.length ? `[${bronzeKeys.join(', ')}]` : '(mark a key)'} />}
            <DRow k={isBronze ? 'source_system_id' : 'source_system_no'} v="100" />
            <DRow k="version" v="1" />
          </div>
        </Section>
      </div>

      {/* Compose + join graph (silver) */}
      {layer === 'silver' && (
        <Section
          title="Composed of"
          hint={isFlat ? 'This Silver is its own table — nothing to compose.' : 'Pick the bronze tables this Silver is built from.'}
        >
          <div className="rounded-md border border-amber-200 bg-amber-50/50 px-3 py-2 text-[11px] text-amber-800 mb-3">
            <b>Lineage, not runtime.</b> The agent queries the single <span className="font-mono">db_table_name</span>; <span className="font-mono">composed_of</span> + <span className="font-mono">join_graph</span> document how it was assembled — never executed at query time.
          </div>
          <label className="flex items-start gap-2 mb-3 text-xs text-gray-700 cursor-pointer">
            <input
              type="checkbox"
              checked={isFlat}
              onChange={(e) => setIsFlat(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              <b>This Silver is a single table</b> — it has no bronze lineage.
              <span className="block text-gray-500">
                Use it for an entity that already exists as one physical table.{' '}
                <span className="font-mono">composed_of</span> is set to{' '}
                <span className="font-mono">{dbTableName.trim() || entityId || 'db_table_name'}</span>{' '}
                and there is no join graph.
              </span>
            </span>
          </label>
          {isFlat ? null : (
          <>
          <div className="flex gap-2 items-center">
            <select value={pickBronze} onChange={(e) => setPickBronze(e.target.value)} className={`${inputCls} flex-1`}>
              <option value="">— pick a bronze table —</option>
              {bronzeOptions.map((b) => <option key={b.id} value={b.id}>{b.name || b.id}</option>)}
            </select>
            <Button variant="outline" size="sm" onClick={() => void addBronze()} disabled={!pickBronze}>＋ Add</Button>
          </div>
          <div className="flex flex-wrap gap-2 mt-2">
            {composed.map((id, i) => (
              <span key={id} className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-[11px] font-mono border ${i === 0 ? 'bg-green-50 border-green-200 text-green-700' : 'bg-gray-100 border-gray-300 text-gray-600'}`}>
                {i === 0 && <span className="text-[9px] font-bold opacity-70">ROOT</span>}
                {tableNameOf(id)}
                {i > 0 && <button onClick={() => removeBronze(i)} className="text-gray-400 hover:text-red-500">✕</button>}
              </span>
            ))}
          </div>

          {joins.length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-1.5 font-semibold">Join graph — condition is yours (key fields hinted)</div>
              <div className="space-y-2">
                {joins.map((j, i) => (
                  <div key={i} className="grid grid-cols-[1fr_1fr_1.1fr_2.4fr_auto] gap-1.5 items-start">
                    <select value={j.left} onChange={(e) => patchJoin(setJoins, i, { left: e.target.value })} className={cellCls}>
                      {composed.map((id) => tableNameOf(id)).filter((n) => n !== j.right).map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                    <input value={j.right} readOnly className={`${cellCls} bg-gray-50 text-gray-500`} />
                    <select value={j.joinType} onChange={(e) => patchJoin(setJoins, i, { joinType: e.target.value })} className={cellCls}>
                      {JOIN_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                    <div className="flex flex-col gap-1">
                      <input value={j.condition} onChange={(e) => patchJoin(setJoins, i, { condition: e.target.value })} placeholder={`${j.left}.KEY = ${j.right}.KEY`} className={`${cellCls} font-mono`} />
                      <div className="flex flex-wrap gap-1">
                        {[...keyFieldsOf(j.left).map((k) => `${j.left}.${k}`), ...keyFieldsOf(j.right).map((k) => `${j.right}.${k}`)].map((chip) => (
                          <button key={chip} onClick={() => patchJoin(setJoins, i, { condition: (j.condition || '') + chip })} className="text-[10px] font-mono border border-blue-200 bg-blue-50 text-blue-600 rounded px-1">{chip}</button>
                        ))}
                        {!j.condition.trim() && <span className="text-[10px] text-amber-600">⚠ write the predicate</span>}
                      </div>
                    </div>
                    <span className="text-[10px] text-gray-400 font-mono pt-1.5">seq {j.sequence}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          </>
          )}
        </Section>
      )}

      {/* Fields */}
      <Section
        title={`Fields (${isBronze ? bronzeFields.length : sgFields.length})`}
        hint="field_role tells the agent where the column may appear in SQL (Standards §5)."
        action={!isBronze ? <AiBtn label="Autocomplete descriptions" onClick={() => void aiAllDescriptions()} disabled={!recipeReady || aiBusy !== null} busy={aiBusy === 'bulk-desc'} /> : undefined}
      >
        {isBronze ? (
          <BronzeFieldsEditor rows={bronzeFields} onChange={setBronzeFields} />
        ) : (
          <SgFieldsEditor rows={sgFields} onChange={setSgFields} onAiField={(i) => void aiFieldDescription(i)} aiBusy={aiBusy} aiEnabled={recipeReady} showSource={layer !== 'gold'} />
        )}
      </Section>

      {/* Relationships (silver + gold) */}
      {!isBronze && (
        <Section title={`Relationships (${rels.length})`} hint="Cross-entity lineage edges → JOIN path-finding. Standards §6-§7.">
          <div className="flex gap-2 items-center mb-2">
            <select value={pickTarget} onChange={(e) => setPickTarget(e.target.value)} className={`${inputCls} flex-1`}>
              <option value="">— pick a target entity —</option>
              {targetOptions.map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}
            </select>
            <Button variant="outline" size="sm" onClick={() => void addRel()} disabled={!pickTarget}>＋ Add</Button>
          </div>
          <RelationshipsList
            rows={rels}
            onChange={setRels}
            onSuggest={(i) => void suggestRel(i)}
            aiBusy={aiBusy}
            thisEntity={{ id: entityId, db_table_name: dbTableName || entityId, fields: draftFields }}
            targetNodes={targetCache}
          />
        </Section>
      )}

      <div className="sticky bottom-0 bg-white border-t border-gray-200 pt-3 flex justify-end gap-2">
        <Button variant="outline" onClick={onClose} disabled={busy}>{t('common_cancel')}</Button>
        <Button onClick={() => void handleSave()} disabled={busy}>
          {busy && <Loader2 size={12} className="animate-spin mr-1.5" />}
          {t('mef_create_btn')}
        </Button>
      </div>
    </div>
  )
}

// ── helpers ────────────────────────────────────────────────────────────────────

function patchJoin(setJoins: Dispatch<SetStateAction<JoinRow[]>>, i: number, patch: Partial<JoinRow>) {
  setJoins((js) => js.map((j, idx) => (idx === i ? { ...j, ...patch } : j)))
}

function errMsg(e: unknown, fallback: string): string {
  const ax = e as { response?: { data?: { detail?: string } }; message?: string }
  return ax.response?.data?.detail ?? ax.message ?? fallback
}

function BronzeFieldsEditor({ rows, onChange }: { rows: BronzeFieldRow[]; onChange: (r: BronzeFieldRow[]) => void }) {
  const set = (i: number, patch: Partial<BronzeFieldRow>) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const toggle = (i: number) =>
    setExpanded((s) => {
      const n = new Set(s)
      if (n.has(i)) n.delete(i)
      else n.add(i)
      return n
    })
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-[1.4fr_1.1fr_1fr_auto_1.6fr_auto] gap-1.5 text-[10px] uppercase tracking-wider text-gray-400 px-1">
        <span>Name</span><span>Type</span><span>Alias</span><span>Key</span><span>Description</span><span />
      </div>
      {rows.map((f, i) => (
        <div key={i}>
          <div className="grid grid-cols-[1.4fr_1.1fr_1fr_auto_1.6fr_auto] gap-1.5 items-center">
            <input value={f.name} onChange={(e) => set(i, { name: e.target.value })} placeholder="VBELN" className={cellCls} />
            <CanonicalTypeSelect value={f.type} onChange={(v) => set(i, { type: v })} />
            <input value={f.alias} onChange={(e) => set(i, { alias: e.target.value })} placeholder="sales_doc" className={cellCls} />
            <input type="checkbox" checked={f.keyField} onChange={(e) => set(i, { keyField: e.target.checked })} className="justify-self-center" />
            <input value={f.description} onChange={(e) => set(i, { description: e.target.value })} className={cellCls} />
            <div className="flex items-center gap-1.5 justify-end">
              <AdvancedToggle open={expanded.has(i)} onClick={() => toggle(i)} />
              <button onClick={() => onChange(rows.filter((_, idx) => idx !== i))} className="text-gray-400 hover:text-red-500"><Trash2 size={13} /></button>
            </div>
          </div>
          {expanded.has(i) && (
            <div className="mt-1">
              <FieldAdvanced layer="bronze" name={f.name} type={f.type} onType={(v) => set(i, { type: v })} />
            </div>
          )}
        </div>
      ))}
      <AddRow onClick={() => onChange([...rows, { name: '', type: 'STRING(10)', alias: '', keyField: false, description: '' }])} />
    </div>
  )
}

function SgFieldsEditor({
  rows, onChange, onAiField, aiBusy, aiEnabled, showSource = true,
}: {
  rows: SgFieldRow[]; onChange: (r: SgFieldRow[]) => void; onAiField: (i: number) => void; aiBusy: string | null; aiEnabled: boolean; showSource?: boolean
}) {
  const set = (i: number, patch: Partial<SgFieldRow>) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const toggle = (i: number) =>
    setExpanded((s) => {
      const n = new Set(s)
      if (n.has(i)) n.delete(i)
      else n.add(i)
      return n
    })
  // Gold has no bronze lineage to declare — hide the column, and nothing is written
  // for it. Silver keeps it (real bronze lineage from the picker).
  // No Key column: a key is field_role: identifier (the Role select) — that's the
  // single control; entity_grain is derived from it.
  const grid = showSource
    ? 'grid-cols-[1.2fr_1.2fr_1fr_1fr_1.7fr_auto] min-w-[640px]'
    : 'grid-cols-[1.4fr_1fr_1fr_1.7fr_auto] min-w-[520px]'
  return (
    <div className="space-y-1.5 overflow-x-auto">
      <div className={`grid ${grid} gap-1.5 text-[10px] uppercase tracking-wider text-gray-400 px-1`}>
        <span>Name</span>{showSource && <span>Source</span>}<span>Type</span><span>Role</span><span>Description (✨)</span><span />
      </div>
      {rows.map((f, i) => {
        const role = f.fieldRole || deriveFieldRoleFromType(f.type)
        return (
          <div key={i}>
            <div className={`grid ${grid} gap-1.5 items-center`}>
              <input value={f.name} onChange={(e) => set(i, { name: e.target.value })} placeholder="net_value" className={cellCls} />
              {showSource && <input value={f.source} onChange={(e) => set(i, { source: e.target.value })} placeholder="VBAK.NETWR" className={`${cellCls} font-mono`} />}
              <CanonicalTypeSelect value={f.type} onChange={(v) => set(i, { type: v })} />
              <select value={f.fieldRole || ''} onChange={(e) => set(i, { fieldRole: e.target.value })} className={cellCls} title={`auto: ${deriveFieldRoleFromType(f.type)} · pick "identifier" to make this a key`}>
                <option value="">{role} (auto)</option>
                {FIELD_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
              <div className="flex items-center gap-1">
                <input value={f.description} onChange={(e) => set(i, { description: e.target.value })} placeholder="description" className={cellCls} />
                <button onClick={() => onAiField(i)} disabled={!aiEnabled || aiBusy !== null} className="text-violet-500 hover:text-violet-700 disabled:opacity-40" title="✨ draft this field">
                  {aiBusy === `field:${i}` ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                </button>
              </div>
              <div className="flex items-center gap-1.5 justify-end">
                <AdvancedToggle open={expanded.has(i)} onClick={() => toggle(i)} />
                <button onClick={() => onChange(rows.filter((_, idx) => idx !== i))} className="text-gray-400 hover:text-red-500"><Trash2 size={13} /></button>
              </div>
            </div>
            {expanded.has(i) && (
              <div className="mt-1">
                <FieldAdvanced
                  layer={showSource ? 'silver' : 'gold'}
                  name={f.name}
                  type={f.type}
                  onType={(v) => set(i, { type: v })}
                  role={role}
                  agg={f.aggregationBehavior}
                  onAgg={(v) => set(i, { aggregationBehavior: v || 'none' })}
                  synonyms={f.synonyms}
                  onSynonyms={(v) => set(i, { synonyms: v })}
                />
              </div>
            )}
          </div>
        )
      })}
      <AddRow label="Add field" onClick={() => onChange([...rows, { name: '', source: '', type: 'STRING(40)', fieldRole: '', aggregationBehavior: 'none', synonyms: [], description: '', sourceTable: '' }])} />
    </div>
  )
}

function RelationshipsList({
  rows, onChange, onSuggest, aiBusy, thisEntity, targetNodes,
}: {
  rows: RelRow[]
  onChange: (r: RelRow[]) => void
  onSuggest: (i: number) => void
  aiBusy: string | null
  thisEntity: { id: string; db_table_name?: string | null; fields: VizField[] }
  targetNodes: Record<string, YAMLNode>
}) {
  const set = (i: number, patch: Partial<RelRow>) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  if (rows.length === 0) return <p className="text-xs text-gray-400 px-1">No relationships — pick a target above, then ✨ Suggest or fill manually.</p>
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="p-2 bg-gray-50 border border-gray-200 rounded space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[11px] text-gray-600 flex-1">{r.targetEntity}</span>
            <button onClick={() => onSuggest(i)} disabled={aiBusy !== null} className="inline-flex items-center gap-1 text-[11px] text-violet-600 border border-violet-200 bg-violet-50 rounded px-2 py-0.5 disabled:opacity-40">
              {aiBusy === `rel:${i}` ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />} Suggest
            </button>
            <button onClick={() => onChange(rows.filter((_, idx) => idx !== i))} className="text-gray-400 hover:text-red-500 px-1"><Trash2 size={13} /></button>
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <select value={r.relationshipType} onChange={(e) => set(i, { relationshipType: e.target.value, aggregationSafety: deriveAggSafety(e.target.value) })} className={cellCls}>
              {REL_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <input value={r.semanticLabel} onChange={(e) => set(i, { semanticLabel: e.target.value })} placeholder="semantic label" className={cellCls} />
            <select value={r.traversalCost} onChange={(e) => set(i, { traversalCost: Number(e.target.value) })} className={cellCls}>
              {COST_PRESETS.map((p) => <option key={p.key} value={p.value}>{p.label}</option>)}
            </select>
          </div>
          <div className="rounded border border-gray-200 bg-white p-1.5">
            <div className="text-[9px] uppercase tracking-wider text-gray-400 mb-1">join condition</div>
            <JoinConditionEditor
              value={r.joinCondition}
              onChange={(v) => set(i, { joinCondition: v })}
              thisEntity={thisEntity}
              targetEntity={targetNodes[r.targetEntity] ?? null}
            />
          </div>
          <div className="grid grid-cols-[1fr_auto_2fr] gap-1.5 items-center">
            <select value={r.aggregationSafety} onChange={(e) => set(i, { aggregationSafety: e.target.value })} className={cellCls}>
              {AGG_SAFETY.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <label className="flex items-center gap-1 text-[11px] text-gray-600 px-1">
              <input type="checkbox" checked={r.crossModule} onChange={(e) => set(i, { crossModule: e.target.checked })} /> cross-module
            </label>
            <input value={r.description} onChange={(e) => set(i, { description: e.target.value })} placeholder="business meaning" className={cellCls} />
          </div>
        </div>
      ))}
    </div>
  )
}

// ── presentational ──────────────────────────────────────────────────────────────

const inputCls = 'w-full text-xs border border-gray-300 rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400'
const cellCls = 'w-full text-xs border border-gray-300 rounded px-1.5 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400'

function AiBtn({ onClick, disabled, busy, label, className }: { onClick: () => void; disabled?: boolean; busy?: boolean; label?: string; className?: string }) {
  return (
    <button onClick={onClick} disabled={disabled} className={`inline-flex items-center gap-1 text-[11px] font-semibold text-violet-600 border border-violet-200 bg-violet-50 rounded px-2 py-1 hover:bg-violet-100 disabled:opacity-40 ${className || ''}`}>
      {busy ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />} {label || 'AI'}
    </button>
  )
}

function DRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-gray-500">{k}</span>
      <span className="font-mono text-gray-700 flex items-center gap-1.5 text-right">
        {v || '—'}
        <span className="text-[9px] font-bold px-1 rounded-full bg-amber-100 border border-amber-200 text-amber-700">auto</span>
      </span>
    </div>
  )
}

function Section({ title, hint, action, children }: { title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5 flex items-center gap-1">
        {title}
        {hint && <span title={hint} className="text-gray-300 hover:text-gray-500 cursor-help"><HelpCircle className="h-3 w-3" /></span>}
        {action && <span className="ml-auto">{action}</span>}
      </h3>
      {children}
    </div>
  )
}

function Labeled({ label, hint, className, children }: { label: string; hint?: string; className?: string; children: ReactNode }) {
  return (
    <label className={`flex flex-col gap-1 ${className || ''}`}>
      <span className="text-[10px] text-gray-500 flex items-center gap-1">
        {label}
        {hint && <span title={hint} className="text-gray-300 cursor-help"><HelpCircle className="h-2.5 w-2.5" /></span>}
      </span>
      {children}
    </label>
  )
}

function AddRow({ onClick, label = 'Add field' }: { onClick: () => void; label?: string }) {
  return (
    <button onClick={onClick} className="self-start inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2 py-1 hover:bg-blue-50">
      <Plus size={12} /> {label}
    </button>
  )
}
