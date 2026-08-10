/**
 * Shared semantic-layer enums + helpers (UX_CHANGES entity-creation redesign).
 *
 * Single source for the constants that were duplicated inline across
 * ManualEntityForm + RelationshipsEditor. Keep in sync with the backend
 * Pydantic literals (ask_knowledge_graph.domain.nodes) + the canonical type
 * vocabulary (ask_knowledge_graph.domain.source_profiles).
 */

export const FIELD_ROLES = [
  'measure',
  'dimension',
  'identifier',
  'timestamp',
  'attribute',
  'status_flag',
] as const
export type FieldRole = (typeof FIELD_ROLES)[number]

export const ENTITY_ROLES = ['fact', 'dimension', 'reference'] as const
export type EntityRoleT = (typeof ENTITY_ROLES)[number]

export const CLASSIFICATIONS = [
  { value: 'M', label: 'M · master' },
  { value: 'T', label: 'T · transactional' },
  { value: 'C', label: 'C · configuration' },
] as const

/**
 * `join_graph[].join_type` — ASK Spec Sec 6.4, standards §4.2. Closed set.
 *
 * `FULL OUTER` is NOT here and must not be added: it appears in no spec section and
 * the backend validator rejects it. `CROSS` is spec-prescribed but not usable as
 * authored today, because `condition` is mandatory on a join row and a CROSS join
 * has no predicate — it is offered for parity with the validator, not because you
 * should reach for it.
 *
 * Single source of truth: both the entity editor and the create form import this.
 * Two hardcoded copies previously disagreed (one offered 3 values, the other 4).
 */
export const JOIN_TYPES = ['INNER', 'LEFT OUTER', 'RIGHT OUTER', 'CROSS'] as const

export const REL_TYPES = [
  'one_to_one',
  'one_to_many',
  'many_to_one',
  'many_to_many',
] as const
export type RelType = (typeof REL_TYPES)[number]

export const AGG_SAFETY = ['safe', 'requires_dedup', 'unsafe'] as const
export type AggSafety = (typeof AGG_SAFETY)[number]

export const AGG_BEHAVIOR = [
  'none',
  'SUM',
  'COUNT',
  'COUNT_DISTINCT',
  'AVG',
  'MIN',
  'MAX',
] as const

export const COST_PRESETS = [
  { key: 'direct', label: 'Direct FK (1)', value: 1 },
  { key: 'indirect', label: 'Indirect (1.5)', value: 1.5 },
  { key: 'cross', label: 'Cross-module (2)', value: 2 },
  { key: 'heavy', label: 'Heavy / dedup (3)', value: 3 },
  { key: 'flattened', label: 'Flattened fallback (4)', value: 4 },
] as const

// Canonical type vocabulary lives in lib/canonicalType.ts (CANONICAL_BASES +
// parse/render), consumed by the CanonicalTypeEditor. The old fixed-preset
// CANONICAL_TYPES list was superseded by that dimension-aware editor.

/** Cardinality → default aggregation safety (lifted from RelationshipsEditor). */
export function deriveAggSafety(relType: string): AggSafety {
  return relType === 'one_to_many' || relType === 'many_to_many'
    ? 'requires_dedup'
    : 'safe'
}
