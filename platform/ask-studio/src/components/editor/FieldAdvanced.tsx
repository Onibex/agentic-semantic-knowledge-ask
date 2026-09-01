/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Settings2 } from 'lucide-react'

import { CanonicalTypeDimensions } from './CanonicalTypeEditor'

/**
 * Field-level Advanced expander, shared by BOTH the New form
 * (ManualEntityForm → Sg/BronzeFieldsEditor) and the global Edit panel
 * (FieldEditor). Rendering the same panel in both is what keeps the two forms
 * at parity: the less-common per-field properties live here, identically.
 *
 * Contents: type dimensions (all layers) + — for Silver/Gold — the two-axis
 * aggregation contract (when the field is a measure) and synonyms.
 * normalization_flag stays parked.
 */

type Layer = 'bronze' | 'silver' | 'gold'

// '' = not curated (the SQL prompt then assumes additive). Axis 1 is a pure SQL
// function; the "may I aggregate at all" question lives in Additivity below.
const AGG_OPTIONS = ['', 'SUM', 'COUNT', 'COUNT_DISTINCT', 'AVG', 'MIN', 'MAX'] as const

// Axis 2 — REQ_ADDITIVITY_CONTRACT.md. '' = additive (the key stays absent).
const ADDITIVITY_OPTIONS = [
  { value: '', label: '— (additive)' },
  { value: 'semi_additive', label: 'semi-additive' },
  { value: 'non_additive', label: 'non-additive' },
] as const

const ADDITIVITY_HINT =
  'Over WHICH dimensions summing is valid. additive: any grouping · ' +
  'semi-additive: collapse the listed dimensions first, then aggregate the rest ' +
  '(a running total, or a value a join repeats — a header amount on every item, ' +
  'a stock level on every movement line) · non-additive: never aggregate ' +
  '(a ratio, a score).'

const selCls =
  'text-xs border border-gray-300 rounded px-1 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400'
const inCls =
  'text-xs border border-gray-300 rounded px-1.5 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400'

const strToList = (s: string) => s.split(',').map((t) => t.trim()).filter(Boolean)

export function AdvancedToggle({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Advanced field options"
      aria-label="Advanced field options"
      className={`shrink-0 rounded p-0.5 ${open ? 'bg-blue-100 text-blue-600' : 'text-gray-400 hover:text-gray-600'}`}
    >
      <Settings2 size={13} />
    </button>
  )
}

export interface FieldAdvancedProps {
  name: string
  layer: Layer
  type: string
  onType: (canonical: string) => void
  /** Effective field_role (Silver/Gold) — Agg shows only for 'measure'. */
  role?: string
  /** Raw aggregation value as the parent stores it ('' or 'none' = none). */
  agg?: string | null
  onAgg?: (value: string) => void
  /** Axis 2 — '' | additive | semi_additive | non_additive. */
  additivity?: string | null
  onAdditivity?: (value: string) => void
  nonAdditiveOver?: string[]
  onNonAdditiveOver?: (value: string[]) => void
  /**
   * Dimensions eligible for `non_additive_over`: the entity's grain fields.
   *
   * v2 (2026-08-03) — ALL of them, not only the `timestamp` ones. v1 restricted
   * this because "collapse to the latest one" is undefined for a non-temporal
   * dimension, which conflated two cases: a value that ACCUMULATES along an
   * ordered dimension does need the latest row, but a value that merely REPEATS
   * because a join fanned the rows out carries the same value on every row of the
   * group, so any one of them is exact. The second case is the ordinary shape of a
   * denormalised Silver, and gating it off here is what forced the instruction into
   * field descriptions where the SQL generator repeatedly misread it.
   *
   * Empty still means the entity has no grain to collapse against, so the option
   * stays disabled rather than offered and then rejected at save time.
   */
  grainDimensions?: string[]
  synonyms?: string[]
  onSynonyms?: (value: string[]) => void
}

export function FieldAdvanced({
  name,
  layer,
  type,
  onType,
  role,
  agg,
  onAgg,
  additivity,
  onAdditivity,
  nonAdditiveOver,
  onNonAdditiveOver,
  grainDimensions,
  synonyms,
  onSynonyms,
}: FieldAdvancedProps) {
  const showSg = layer !== 'bronze'
  const isMeasure = (role ?? '') === 'measure'
  const addVal = additivity ?? ''
  const isNonAdditive = addVal === 'non_additive'
  const isSemiAdditive = addVal === 'semi_additive'
  const candidates = grainDimensions ?? []
  const selectedOver = nonAdditiveOver ?? []
  // A non-additive measure must carry `aggregation_behavior: none` (the model
  // rejects anything else), so the function select is pinned rather than left
  // free to produce a save-time 422.
  const aggVal = isNonAdditive ? 'none' : agg && agg !== 'none' ? agg : ''

  const setAdditivity = (value: string) => {
    onAdditivity?.(value)
    // Keep the two axes consistent as the user moves between them.
    if (value === 'non_additive') onAgg?.('none')
    else if (isNonAdditive) onAgg?.('')
    if (value !== 'semi_additive') onNonAdditiveOver?.([])
  }

  const toggleOver = (dim: string) =>
    onNonAdditiveOver?.(
      selectedOver.includes(dim)
        ? selectedOver.filter((d) => d !== dim)
        : [...selectedOver, dim],
    )

  return (
    <div className="rounded border border-gray-200 bg-gray-50 p-2 flex flex-wrap items-center gap-x-4 gap-y-2">
      <span className="text-[10px] uppercase tracking-wider text-gray-400">
        Advanced — <span className="font-mono normal-case text-gray-600">{name || 'field'}</span>
      </span>

      <CanonicalTypeDimensions value={type} onChange={onType} />

      {showSg && isMeasure && onAgg && (
        <label className="flex items-center gap-1 text-[10px] text-gray-600">
          Aggregation
          <select
            value={aggVal}
            onChange={(e) => onAgg(e.target.value)}
            disabled={isNonAdditive}
            title={
              isNonAdditive
                ? 'Pinned to none: a non-additive measure has no aggregation function.'
                : 'Which SQL function to apply when this measure is aggregated.'
            }
            className={`${selCls} ${isNonAdditive ? 'opacity-60' : ''}`}
          >
            {isNonAdditive && <option value="none">none</option>}
            {AGG_OPTIONS.map((a) => (
              <option key={a} value={a}>
                {a || '— (uncurated)'}
              </option>
            ))}
          </select>
        </label>
      )}

      {showSg && isMeasure && onAdditivity && (
        <label className="flex items-center gap-1 text-[10px] text-gray-600">
          Additivity
          <select
            value={addVal}
            onChange={(e) => setAdditivity(e.target.value)}
            title={ADDITIVITY_HINT}
            className={selCls}
          >
            {ADDITIVITY_OPTIONS.map((o) => (
              <option
                key={o.value}
                value={o.value}
                disabled={o.value === 'semi_additive' && candidates.length === 0}
              >
                {o.label}
              </option>
            ))}
          </select>
        </label>
      )}

      {showSg && isMeasure && isSemiAdditive && onNonAdditiveOver && (
        <span className="flex items-center gap-1.5 text-[10px] text-gray-600">
          <span title="Collapse these first (one row per grain group: the latest row when the dimension is temporal, any one row when a join merely repeats the value), then aggregate across the rest.">
            Collapse first
          </span>
          {candidates.length === 0 ? (
            <em className="text-amber-700">
              this entity declares no grain to collapse against
            </em>
          ) : (
            candidates.map((dim) => (
              <label key={dim} className="flex items-center gap-0.5 font-mono">
                <input
                  type="checkbox"
                  checked={selectedOver.includes(dim)}
                  onChange={() => toggleOver(dim)}
                />
                {dim}
              </label>
            ))
          )}
        </span>
      )}

      {showSg && onSynonyms && (
        <label className="flex items-center gap-1 text-[10px] text-gray-600">
          Synonyms
          <input
            value={(synonyms ?? []).join(', ')}
            onChange={(e) => onSynonyms(strToList(e.target.value))}
            placeholder="alt names…"
            title="Comma-separated alternative names to boost retrieval / disambiguation"
            className={inCls}
          />
        </label>
      )}
    </div>
  )
}
