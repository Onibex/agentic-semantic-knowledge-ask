/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { Plus, Type, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { useTranslation } from '../../hooks/useTranslation'
import {
  composeJoin,
  defaultAlias,
  JOIN_OPS,
  parseJoin,
  type JoinOp,
  type JoinPair,
} from './joinExpression'
import type { VizField, YAMLNode } from '../../api/types'

interface Props {
  /** Current raw SQL value (canonical). The editor parses it; emits it back via onChange. */
  value: string
  onChange(next: string): void

  /** The entity being edited — drives the LEFT-side picker + default alias. */
  thisEntity: { id: string; db_table_name?: string | null; fields: VizField[] }

  /** The target entity, if resolvable from the workspace catalogue. */
  targetEntity: YAMLNode | null
}

/**
 * Edit a join condition either as a list of column pairs (compact mode) or
 * as free SQL (expert mode). Compact mode covers ≥90% of real relationships
 * (FK chains made of N AND'd equality clauses). Expert mode opens
 * automatically when the parser sees casts / OR / parens / etc.
 *
 * Aliases are surfaced as editable inputs — the editor never silently
 * normalizes them so existing data round-trips byte-for-byte.
 */
export function JoinConditionEditor({ value, onChange, thisEntity, targetEntity }: Props) {
  const { t } = useTranslation()
  // Parse on the way in. We keep the editor state as `pairs + aliases`
  // and recompose on every change — the canonical truth stays the SQL
  // string the parent owns.
  const parsed = useMemo(() => parseJoin(value), [value])

  const [expertMode, setExpertMode] = useState<boolean>(parsed.expert)
  const [rawSql, setRawSql] = useState<string>(value)
  const [thisAlias, setThisAlias] = useState<string>(() =>
    parsed.expert ? defaultAlias(thisEntity) : parsed.thisAlias || defaultAlias(thisEntity),
  )
  const [targetAlias, setTargetAlias] = useState<string>(() =>
    parsed.expert
      ? defaultAlias(targetEntity)
      : parsed.targetAlias || defaultAlias(targetEntity),
  )
  const [pairs, setPairs] = useState<JoinPair[]>(() =>
    parsed.expert
      ? [emptyPair()]
      : parsed.pairs.length > 0
      ? parsed.pairs
      : [emptyPair()],
  )

  // Re-sync local state when the canonical value changes externally
  // (e.g. AI Suggest later, or another relationship card being focused).
  useEffect(() => {
    const fresh = parseJoin(value)
    if (fresh.expert) {
      setExpertMode(true)
      setRawSql(value)
    } else {
      setExpertMode(false)
      setRawSql(value)
      setThisAlias(fresh.thisAlias || defaultAlias(thisEntity))
      setTargetAlias(fresh.targetAlias || defaultAlias(targetEntity))
      setPairs(fresh.pairs.length > 0 ? fresh.pairs : [emptyPair()])
    }
    // We intentionally trigger only on the canonical value — local edits
    // call onChange themselves and the parent re-renders with the new value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  // ─ Compact-mode mutators ────────────────────────────────────────────────

  function commit(nextPairs: JoinPair[], aliases?: { thisA?: string; targetA?: string }) {
    const tA = aliases?.thisA ?? thisAlias
    const xA = aliases?.targetA ?? targetAlias
    onChange(composeJoin(tA, xA, nextPairs))
  }

  function updatePair(i: number, patch: Partial<JoinPair>) {
    const next = pairs.map((p, idx) => (idx === i ? { ...p, ...patch } : p))
    setPairs(next)
    commit(next)
  }
  function addPair() {
    const next = [...pairs, emptyPair()]
    setPairs(next)
    // Don't commit — empty pair won't change the SQL anyway.
  }
  function removePair(i: number) {
    const next = pairs.filter((_, idx) => idx !== i)
    const ensured = next.length > 0 ? next : [emptyPair()]
    setPairs(ensured)
    commit(ensured)
  }
  function toggleRightKind(i: number) {
    // Switching kinds clears the right-side value so we don't carry a field
    // name into a literal slot (or vice versa) — would always be a bug.
    const p = pairs[i]
    const nextKind = p.rightKind === 'field' ? 'literal' : 'field'
    updatePair(i, { rightKind: nextKind, targetField: '' })
  }
  function changeAlias(side: 'this' | 'target', v: string) {
    if (side === 'this') {
      setThisAlias(v)
      commit(pairs, { thisA: v })
    } else {
      setTargetAlias(v)
      commit(pairs, { targetA: v })
    }
  }

  // ─ Expert-mode mutators ─────────────────────────────────────────────────

  function changeRawSql(v: string) {
    setRawSql(v)
    onChange(v)
  }

  function tryReturnToCompact() {
    const re = parseJoin(rawSql)
    if (re.expert) {
      // Still complex — keep expert.
      return false
    }
    setExpertMode(false)
    setThisAlias(re.thisAlias || defaultAlias(thisEntity))
    setTargetAlias(re.targetAlias || defaultAlias(targetEntity))
    setPairs(re.pairs.length > 0 ? re.pairs : [emptyPair()])
    return true
  }

  function switchToExpert() {
    setExpertMode(true)
    // Make sure rawSql reflects the current compact state before letting
    // the user edit it freely.
    setRawSql(composeJoin(thisAlias, targetAlias, pairs))
  }

  // ─ Field options ────────────────────────────────────────────────────────

  const thisFieldNames = useMemo(
    () => thisEntity.fields.map((f) => f.name).sort(),
    [thisEntity.fields],
  )
  const targetFieldNames = useMemo(
    () => (targetEntity?.fields ?? []).map((f) => f.name).sort(),
    [targetEntity?.fields],
  )

  // ─ Render ───────────────────────────────────────────────────────────────

  if (expertMode) {
    return (
      <div className="flex flex-col gap-1.5">
        <textarea
          rows={2}
          value={rawSql}
          onChange={(e) => changeRawSql(e.target.value)}
          placeholder="A.col = B.col [AND ...]"
          className="text-xs border border-amber-300 rounded px-1.5 py-0.5 font-mono bg-amber-50/40 focus:outline-none focus:ring-1 focus:ring-amber-400 resize-y"
        />
        <div className="flex items-center justify-between text-[10px] text-gray-500">
          <span className="text-amber-700">
            {t('jce_expert_hint')}
          </span>
          <button
            type="button"
            onClick={tryReturnToCompact}
            className="text-blue-600 hover:underline"
            title="If the SQL is N AND-separated equalities, switch back to the picker UI"
          >
            <Wand2 className="h-3 w-3 inline mr-1" />
            {t('jce_try_compact')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1.5">
      {/* Alias row — usually unchanged but exposed for the rare cases where
          existing entities use short aliases. */}
      <div className="grid grid-cols-2 gap-1.5">
        <input
          type="text"
          value={thisAlias}
          onChange={(e) => changeAlias('this', e.target.value)}
          placeholder="THIS alias"
          title="Alias used for THIS entity in the SQL. Default = entity id uppercased."
          className="text-[10px] border border-gray-200 rounded px-1.5 py-0.5 font-mono bg-gray-50 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <input
          type="text"
          value={targetAlias}
          onChange={(e) => changeAlias('target', e.target.value)}
          placeholder="TARGET alias"
          title="Alias used for the TARGET entity in the SQL. Default = target id uppercased."
          className="text-[10px] border border-gray-200 rounded px-1.5 py-0.5 font-mono bg-gray-50 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>

      {/* Pair rows */}
      {pairs.map((pair, i) => (
        <div
          key={i}
          className="grid gap-1 items-center"
          style={{ gridTemplateColumns: '1fr auto 1fr auto auto' }}
        >
          {/* LEFT picker — this entity's fields */}
          <FieldPicker
            value={pair.thisField}
            options={thisFieldNames}
            onChange={(v) => updatePair(i, { thisField: v })}
            placeholder="this.field"
          />

          {/* Operator */}
          <select
            value={pair.op}
            onChange={(e) => updatePair(i, { op: e.target.value as JoinOp })}
            title="Comparison operator. Equality (=) covers most FK joins; <> / != / range ops only for conditional predicates on this side."
            className="text-xs border border-gray-300 rounded px-1 py-0.5 font-mono bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            {JOIN_OPS.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>

          {/* RIGHT — either a field picker or a literal input. */}
          {pair.rightKind === 'field' ? (
            <FieldPicker
              value={pair.targetField}
              options={targetFieldNames}
              onChange={(v) => updatePair(i, { targetField: v })}
              placeholder={targetEntity ? 'target.field' : 'pick target first'}
              disabled={!targetEntity}
            />
          ) : (
            <input
              type="text"
              value={pair.targetField}
              onChange={(e) => updatePair(i, { targetField: e.target.value })}
              placeholder="'literal' or 100"
              title="Verbatim literal. Wrap strings in single quotes ('BLOCKED'); numbers go bare (100)."
              className="text-xs border border-gray-300 rounded px-1.5 py-0.5 font-mono bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 min-w-0 w-full"
            />
          )}

          {/* Right-kind toggle: field ↔ literal */}
          <button
            type="button"
            onClick={() => toggleRightKind(i)}
            className={`text-[10px] border rounded px-1 py-0.5 inline-flex items-center gap-0.5 transition-colors ${
              pair.rightKind === 'literal'
                ? 'border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100'
                : 'border-gray-300 bg-white text-gray-500 hover:bg-gray-50'
            }`}
            title={
              pair.rightKind === 'field'
                ? 'Switch right side to a literal value (e.g. \'100\', \'BLOCKED\').'
                : 'Switch right side back to a field picker.'
            }
          >
            <Type className="h-3 w-3" />
            {pair.rightKind === 'literal' ? 'lit' : 'fld'}
          </button>

          <button
            type="button"
            onClick={() => removePair(i)}
            disabled={pairs.length === 1 && !pair.thisField && !pair.targetField}
            className="text-gray-400 hover:text-red-500 text-base leading-none px-1 disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Remove pair"
            title="Remove this clause"
          >
            ×
          </button>
        </div>
      ))}

      <div className="flex items-center justify-between text-[10px]">
        <button
          type="button"
          onClick={addPair}
          className="text-blue-600 hover:text-blue-800 inline-flex items-center gap-0.5"
          title="Composite key: AND another column pair"
        >
          <Plus className="h-3 w-3" /> {t('jce_add_column_pair')}
        </button>
        <button
          type="button"
          onClick={switchToExpert}
          className="text-gray-500 hover:text-gray-700"
          title="Switch to free-SQL editor (casts, OR-logic, multi-table joins)"
        >
          {t('jce_expert_sql')}
        </button>
      </div>

      {/* Live preview of the composed SQL so the admin sees exactly what
          gets persisted. Small + greyed out — informational, not editable. */}
      {pairs.some((p) => p.thisField || p.targetField) && (
        <div
          className="text-[10px] font-mono text-gray-500 bg-white border border-gray-100 rounded px-1.5 py-0.5 truncate"
          title="Composed SQL preview"
        >
          {composeJoin(thisAlias, targetAlias, pairs) || (
            <span className="italic text-gray-400">{t('jce_incomplete')}</span>
          )}
        </div>
      )}
    </div>
  )
}

// ── Sub-component: a select that falls back to a datalist + input when the
//    value isn't in the option list (preserves existing data unchanged) ────

interface FieldPickerProps {
  value: string
  options: string[]
  onChange(v: string): void
  placeholder?: string
  disabled?: boolean
}

function FieldPicker({ value, options, onChange, placeholder, disabled }: FieldPickerProps) {
  // A native datalist gives us: free typing + autocomplete against options.
  // Using a plain `<select>` would silently drop the value if it isn't in
  // the list (and existing joins reference field names that may have been
  // renamed since). datalist preserves the user's text either way.
  const listId = `fp-${Math.abs(hashCode(options.join(',') + (placeholder ?? '')))}`
  return (
    <>
      <input
        list={listId}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="text-xs border border-gray-300 rounded px-1.5 py-0.5 font-mono bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 min-w-0 w-full disabled:opacity-50"
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </>
  )
}

// Fresh empty pair — default kind is field (the 90% case) and op `=`
// (also the 90% case). Centralized so the UI doesn't drift from the parser
// shape if we add fields later.
function emptyPair(): JoinPair {
  return { thisField: '', op: '=', rightKind: 'field', targetField: '' }
}

// Tiny deterministic hash so multiple pickers on the same page don't collide
// on datalist ids without needing a global counter / nanoid.
function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i)
    h |= 0
  }
  return h
}
