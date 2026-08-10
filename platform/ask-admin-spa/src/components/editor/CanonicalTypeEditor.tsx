import {
  CANONICAL_BASES,
  type CanonicalBase,
  type CanonicalParts,
  DEFAULT_DIMS,
  parseCanonicalType,
  renderCanonicalType,
} from '@/lib/canonicalType'

/**
 * Canonical data-type controls for Bronze / Silver / Gold fields. The same
 * vocabulary backs all three layers (see lib/canonicalType.ts).
 *
 * Two pieces, used together but at different altitudes:
 *  - <CanonicalTypeSelect> — INLINE in the field's type cell: base dropdown + a
 *    chip showing the rendered canonical WITH its dimensions, so the default is
 *    visible at a glance. No advanced control here (keeps the cell compact, and
 *    avoids the gear overlapping the narrow grid column).
 *  - <CanonicalTypeDimensions> — the dimension editor, rendered in the FIELD-level
 *    Advanced panel (a per-row expander). STRING → length; DECIMAL → precision /
 *    scale; other bases have none. This is the seam for future per-type field
 *    options (nullable, SAP sentinels, per-dialect overrides) — DB-dialect
 *    rendering stays in the SQL-gen prompts; the stored type remains canonical.
 *
 * Both emit the canonical string (e.g. "STRING(10)", "DECIMAL(15,2)", "DATE");
 * the backend re-canonicalizes idempotently on save.
 */

const selCls =
  'text-xs border border-gray-300 rounded px-1 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400'
const numCls =
  'w-16 text-xs border border-gray-300 rounded px-1 py-0.5 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400'

function posInt(v: string): number | undefined {
  const n = parseInt(v, 10)
  return Number.isFinite(n) && n > 0 ? n : undefined
}
function nonNegInt(v: string): number | undefined {
  const n = parseInt(v, 10)
  return Number.isFinite(n) && n >= 0 ? n : undefined
}

/** Inline type control: base dropdown + canonical chip (with dimensions). */
export function CanonicalTypeSelect({
  value,
  onChange,
}: {
  value: string
  onChange: (canonical: string) => void
}) {
  const parts = parseCanonicalType(value)
  const rendered = renderCanonicalType(parts)
  // Switching base applies that base's sensible default dims, so the chip shows
  // a usable type immediately (no need to open Advanced).
  const changeBase = (base: CanonicalBase) =>
    onChange(renderCanonicalType({ base, ...(DEFAULT_DIMS[base] ?? {}) }))

  return (
    <div className="flex items-center gap-1 min-w-0">
      <select
        value={parts.base}
        onChange={(e) => changeBase(e.target.value as CanonicalBase)}
        className={selCls}
      >
        {CANONICAL_BASES.map((b) => (
          <option key={b} value={b}>
            {b}
          </option>
        ))}
      </select>
      <span className="font-mono text-[10px] text-gray-500 truncate" title={rendered}>
        {rendered}
      </span>
    </div>
  )
}

/** Dimension editor for the field-level Advanced panel. */
export function CanonicalTypeDimensions({
  value,
  onChange,
}: {
  value: string
  onChange: (canonical: string) => void
}) {
  const parts = parseCanonicalType(value)
  const rendered = renderCanonicalType(parts)
  const emit = (next: CanonicalParts) => onChange(renderCanonicalType(next))

  if (parts.base === 'STRING') {
    return (
      <div className="flex items-center gap-2 text-[10px] text-gray-600">
        <label className="flex items-center gap-1">
          Length
          <input
            type="number"
            min={1}
            value={parts.length ?? ''}
            placeholder="∞"
            onChange={(e) => emit({ base: 'STRING', length: posInt(e.target.value) })}
            className={numCls}
          />
        </label>
        <span className="text-gray-400">blank = unbounded</span>
        <span className="font-mono text-blue-600">→ {rendered}</span>
      </div>
    )
  }

  if (parts.base === 'DECIMAL') {
    return (
      <div className="flex items-center gap-2 text-[10px] text-gray-600">
        <label className="flex items-center gap-1">
          Precision
          <input
            type="number"
            min={1}
            value={parts.precision ?? ''}
            onChange={(e) =>
              emit({ base: 'DECIMAL', precision: posInt(e.target.value), scale: parts.scale })
            }
            className={numCls}
          />
        </label>
        <label className="flex items-center gap-1">
          Scale
          <input
            type="number"
            min={0}
            value={parts.scale ?? ''}
            onChange={(e) =>
              emit({ base: 'DECIMAL', precision: parts.precision, scale: nonNegInt(e.target.value) })
            }
            className={numCls}
          />
        </label>
        <span className="font-mono text-blue-600">→ {rendered}</span>
      </div>
    )
  }

  return <span className="text-[10px] text-gray-400">No type dimensions for {parts.base}.</span>
}
