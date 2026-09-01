/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Tiny parser / composer for ON-clause SQL strings used by relationships.
 *
 * Goal: let the SPA edit a join condition as a list of clauses where each
 * clause is ``A.col <op> X``, with X being either ``B.col`` (field-to-field)
 * or a verbatim literal (string, number, etc.). Clauses are AND-separated.
 *
 * Anything more exotic (OR, IS NULL, IN, casts, parentheses) falls back to
 * expert mode and round-trips verbatim.
 *
 * Round-trip contract:
 *   parseJoin(s) → if compact-friendly, returns the pairs + the two aliases
 *                  used (preserving whatever the admin wrote).
 *               → otherwise returns {expert: true, raw: s} verbatim.
 *   composeJoin(thisAlias, targetAlias, pairs) → flat SQL string.
 *
 * Keeping the aliases as captured (instead of normalizing them) means the
 * editor doesn't rewrite existing joins behind the user's back — important
 * because in practice we've seen entities use both their full id
 * ("SILVER_S4H_SD_SALES_ORDER") AND short aliases ("SILVER_TRADING_GOODS")
 * in the same workspace.
 */

/** Binary comparison operators supported in compact mode. */
export type JoinOp = '=' | '<>' | '!=' | '<' | '<=' | '>' | '>='

export const JOIN_OPS: readonly JoinOp[] = ['=', '<>', '!=', '<', '<=', '>', '>='] as const

/**
 * Whether the right-hand side of the clause is another column (joined to
 * the target entity) or a verbatim literal (`'100'`, `42`, `'BLOCKED'`).
 * Literals are stored EXACTLY as the admin typed them — we don't try to
 * quote/escape them, so existing SQL round-trips unchanged.
 */
export type JoinRightKind = 'field' | 'literal'

export interface JoinPair {
  thisField: string
  op: JoinOp
  rightKind: JoinRightKind
  /** Field name when rightKind='field', verbatim text when rightKind='literal'. */
  targetField: string
}

export interface CompactJoin {
  expert: false
  thisAlias: string
  targetAlias: string
  pairs: JoinPair[]
}

export interface ExpertJoin {
  expert: true
  raw: string
}

export type ParsedJoin = CompactJoin | ExpertJoin

/** Identifier we'll accept on either side of the dot. Matches SAP-like names. */
const IDENT = '[A-Za-z_][A-Za-z0-9_]*'

// Operator pattern — order matters: longer alternatives first so `<=` is not
// captured as `<` then `=`.
const OP_PATTERN = '<>|!=|<=|>=|=|<|>'

/**
 * Capture groups:
 *   1 = left alias
 *   2 = left column
 *   3 = operator
 *   4 = right side (verbatim — we sub-parse it for `<alias>.<col>` vs literal)
 */
const CLAUSE_RE = new RegExp(`^(${IDENT})\\.(${IDENT})\\s*(${OP_PATTERN})\\s*(.+?)\\s*$`)
const RIGHT_FIELD_RE = new RegExp(`^(${IDENT})\\.(${IDENT})$`)

/**
 * Parse an ON-clause SQL string into pairs.
 *
 * Compact mode requires:
 *   - every AND-separated clause is exactly ``ident.ident <op> RHS``
 *     where RHS is either ``ident.ident`` (field) or anything else (literal).
 *   - every left-side uses the SAME alias (this entity).
 *   - every clause whose RHS IS a field reference uses the SAME right-side
 *     alias (target entity). Literal-RHS clauses don't constrain the target
 *     alias — they're just predicates on this entity's column.
 *
 * Anything else falls back to expert mode and is preserved verbatim.
 */
export function parseJoin(raw: string | null | undefined): ParsedJoin {
  const text = (raw ?? '').trim()
  if (!text) {
    return { expert: false, thisAlias: '', targetAlias: '', pairs: [] }
  }

  // Reject quickly when the giveaways of free SQL appear. OR / IS / IN /
  // CAST / parens / etc. all push us to expert mode.
  if (/\bOR\b|\bIS\b|\bIN\b|\bCASE\b|\bCAST\b|\bCOALESCE\b|\(|\)|--|::/i.test(text)) {
    return { expert: true, raw: text }
  }

  const clauses = text
    .split(/\s+AND\s+/i)
    .map((c) => c.trim())
    .filter(Boolean)

  if (clauses.length === 0) {
    return { expert: false, thisAlias: '', targetAlias: '', pairs: [] }
  }

  let thisAlias: string | null = null
  let targetAlias: string | null = null
  const pairs: JoinPair[] = []

  for (const clause of clauses) {
    const m = clause.match(CLAUSE_RE)
    if (!m) return { expert: true, raw: text }
    const [, leftAlias, leftCol, op, rhs] = m

    if (thisAlias === null) thisAlias = leftAlias
    if (leftAlias !== thisAlias) {
      // The LHS alias differs across clauses — that's a multi-table join.
      // Compact mode is two-entity only; bail to expert.
      return { expert: true, raw: text }
    }

    // Determine RHS shape.
    const rhsField = rhs.match(RIGHT_FIELD_RE)
    if (rhsField) {
      const [, rightAlias, rightCol] = rhsField
      if (targetAlias === null) targetAlias = rightAlias
      if (rightAlias !== targetAlias) {
        // RHS alias differs across clauses — also multi-table. Bail.
        return { expert: true, raw: text }
      }
      pairs.push({
        thisField: leftCol,
        op: op as JoinOp,
        rightKind: 'field',
        targetField: rightCol,
      })
    } else {
      pairs.push({
        thisField: leftCol,
        op: op as JoinOp,
        rightKind: 'literal',
        targetField: rhs, // verbatim
      })
    }
  }

  return {
    expert: false,
    thisAlias: thisAlias ?? '',
    targetAlias: targetAlias ?? '',
    pairs,
  }
}

/**
 * Compose a flat SQL ON-clause from the compact-mode state.
 * Half-filled pairs are dropped so we never emit "A.col = ".
 */
export function composeJoin(
  thisAlias: string,
  targetAlias: string,
  pairs: JoinPair[],
): string {
  const parts: string[] = []
  for (const p of pairs) {
    const lhs = p.thisField.trim()
    const rhs = p.targetField.trim()
    if (!lhs || !rhs) continue
    const leftExpr = `${thisAlias}.${lhs}`
    const rightExpr = p.rightKind === 'field' ? `${targetAlias}.${rhs}` : rhs
    parts.push(`${leftExpr} ${p.op} ${rightExpr}`)
  }
  return parts.join(' AND ')
}

/**
 * Convenience: derive a sensible default alias for an entity. We prefer the
 * physical table name (``db_table_name``) when it's populated — that's what
 * the SQL executor actually sees, so the JOIN written here lands in
 * downstream queries with zero translation. When the field is missing
 * (legacy YAMLs), we fall back to the entity id uppercased so existing data
 * round-trips unchanged.
 */
export function defaultAlias(
  entity: { id?: string | null; db_table_name?: string | null } | null | undefined,
): string {
  if (!entity) return ''
  const physical = (entity.db_table_name ?? '').trim()
  if (physical) return physical
  return (entity.id ?? '').toUpperCase()
}
