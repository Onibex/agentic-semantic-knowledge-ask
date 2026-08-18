/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Canonical data-type vocabulary + parser/renderer for the ASK semantic layer.
 *
 * Single front-end mirror of the backend authority,
 * `packages/ask-knowledge-graph/src/ask_knowledge_graph/domain/source_profiles.py`
 * (`CanonicalType` + `TypeMapper`). The type stored in YAML is source-agnostic;
 * supporting other databases is a SQL-gen / prompt concern (per-dialect prompts),
 * NOT a different stored type — so this vocabulary is the standard for bronze,
 * silver AND gold. Keep these tables in sync with `source_profiles.py`.
 *
 * Tolerant + idempotent: accepts SAP codes (`C10`), SQL keywords (`VARCHAR(10)`)
 * and canonical (`STRING(10)`), and `toCanonicalType(render(parse(x))) == ...`.
 */

export const CANONICAL_BASES = [
  'STRING',
  'INTEGER',
  'DECIMAL',
  'DATE',
  'TIMESTAMP',
  'BOOLEAN',
] as const
export type CanonicalBase = (typeof CANONICAL_BASES)[number]

export interface CanonicalParts {
  base: CanonicalBase
  length?: number // STRING only
  precision?: number // DECIMAL only
  scale?: number // DECIMAL only
}

// DDIC / SQL keyword aliases (raw word → canonical base). Mirror of
// source_profiles._KEYWORD_BASE.
const KEYWORD_BASE: Record<string, CanonicalBase> = {
  STRING: 'STRING', INTEGER: 'INTEGER', DECIMAL: 'DECIMAL', DATE: 'DATE',
  TIMESTAMP: 'TIMESTAMP', BOOLEAN: 'BOOLEAN',
  // SQL strings
  VARCHAR: 'STRING', VARCHAR2: 'STRING', NVARCHAR: 'STRING', NVARCHAR2: 'STRING',
  CHAR: 'STRING', NCHAR: 'STRING', TEXT: 'STRING', CLOB: 'STRING',
  // SQL integers
  INT: 'INTEGER', INT2: 'INTEGER', INT4: 'INTEGER', INT8: 'INTEGER',
  BIGINT: 'INTEGER', SMALLINT: 'INTEGER', TINYINT: 'INTEGER', SERIAL: 'INTEGER',
  // SQL numerics
  NUMERIC: 'DECIMAL', NUMBER: 'DECIMAL', DEC: 'DECIMAL', FLOAT: 'DECIMAL',
  DOUBLE: 'DECIMAL', REAL: 'DECIMAL', MONEY: 'DECIMAL',
  // SQL temporals / booleans
  DATETIME: 'TIMESTAMP', TIMESTAMPTZ: 'TIMESTAMP', BOOL: 'BOOLEAN', BIT: 'BOOLEAN',
  // DDIC datatypes (multi-char)
  DATS: 'DATE', TIMS: 'STRING', NUMC: 'STRING', CUKY: 'STRING', UNIT: 'STRING',
  LANG: 'STRING', CLNT: 'STRING', CURR: 'DECIMAL', QUAN: 'DECIMAL', FLTP: 'DECIMAL',
  RAW: 'STRING', SSTRING: 'STRING', STRG: 'STRING',
}

// SAP ABAP single-char "internal type" codes. Mirror of source_profiles._SAP_INTTYPE.
const SAP_INTTYPE: Record<string, CanonicalBase> = {
  C: 'STRING', N: 'STRING', G: 'STRING', X: 'STRING', Y: 'STRING', D: 'DATE',
  T: 'STRING', P: 'DECIMAL', F: 'DECIMAL', A: 'DECIMAL', E: 'DECIMAL',
  I: 'INTEGER', S: 'INTEGER', B: 'INTEGER',
}

/** Sensible defaults applied when the user switches the base, so the inline view
 *  shows a usable dimension without the user having to touch it. Tune here. */
export const DEFAULT_DIMS: Partial<Record<CanonicalBase, Omit<CanonicalParts, 'base'>>> = {
  STRING: { length: 40 },
  DECIMAL: { precision: 15, scale: 2 },
}

const PAREN_RE = /^\s*([A-Za-z][A-Za-z0-9_]*)\s*\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)\s*$/
const BARE_RE = /^\s*([A-Za-z][A-Za-z0-9_]*?)\s*$/
const SAP_CODE_RE = /^\s*([A-Za-z])\s*(\d+)\s*$/

function withParams(base: CanonicalBase, a?: number, b?: number): CanonicalParts {
  if (base === 'STRING') return { base, length: a || undefined }
  if (base === 'DECIMAL') return { base, precision: a || undefined, scale: b }
  return { base } // INTEGER / DATE / TIMESTAMP / BOOLEAN ignore params
}

/** Parse any raw type (SAP / SQL / canonical) into its canonical parts. Never throws;
 *  unknown input falls back to STRING (matches the backend). */
export function parseCanonicalType(raw: string | null | undefined): CanonicalParts {
  const s = (raw ?? '').trim()
  if (!s) return { base: 'STRING' }

  // 1. Parenthesized keyword: STRING(10) / VARCHAR(10) / DECIMAL(15,2)
  let m = PAREN_RE.exec(s)
  if (m) {
    const base = KEYWORD_BASE[m[1].toUpperCase()]
    if (base) return withParams(base, Number(m[2]), m[3] != null ? Number(m[3]) : undefined)
  }
  // 2. Bare keyword / single-char SAP inttype with no length
  m = BARE_RE.exec(s)
  if (m) {
    const w = m[1].toUpperCase()
    if (KEYWORD_BASE[w]) return { base: KEYWORD_BASE[w] }
    if (w.length === 1 && SAP_INTTYPE[w]) return { base: SAP_INTTYPE[w] }
  }
  // 3. SAP single-char code + length: C10, P15, D8, N6
  m = SAP_CODE_RE.exec(s)
  if (m) {
    const base = SAP_INTTYPE[m[1].toUpperCase()]
    if (base) return withParams(base, Number(m[2]), undefined)
  }
  // 4. Unknown → STRING
  return { base: 'STRING' }
}

/** Render canonical parts to the authoritative string stored in YAML. */
export function renderCanonicalType(p: CanonicalParts): string {
  if (p.base === 'STRING') return p.length ? `STRING(${p.length})` : 'STRING'
  if (p.base === 'DECIMAL') {
    if (p.precision && p.scale != null && p.scale > 0) return `DECIMAL(${p.precision},${p.scale})`
    if (p.precision) return `DECIMAL(${p.precision})`
    return 'DECIMAL'
  }
  return p.base
}

/** Convenience: raw (any dialect) → canonical string. */
export function toCanonicalType(raw: string | null | undefined): string {
  return renderCanonicalType(parseCanonicalType(raw))
}

/** Field-role hint from a type (DECIMAL→measure, DATE/TIMESTAMP→timestamp, else
 *  dimension). Mirrors EntityDeriver.field_role_for_canonical. */
export function deriveFieldRoleFromType(type: string | null | undefined): string {
  const b = parseCanonicalType(type).base
  if (b === 'DECIMAL') return 'measure'
  if (b === 'DATE' || b === 'TIMESTAMP') return 'timestamp'
  return 'dimension'
}
