import type { VizJoinCondition } from '../../api/types';
import { JOIN_TYPES } from '../../lib/semanticConstants';

interface JoinGraphEditorProps {
  conditions: VizJoinCondition[];
  onChange(conditions: VizJoinCondition[]): void;
  /**
   * When true, the editor renders as a non-interactive view of the join
   * conditions. Used for Silver entities where the join graph is sourced
   * from SAP (Spark JSON ingest) and must NOT be hand-edited — drift here
   * silently corrupts SQL generation downstream. The admin can still
   * inspect what's there; edits go through re-ingesting the SAP JSON.
   */
  readOnly?: boolean;
}

// JOIN_TYPES comes from lib/semanticConstants — do not redeclare it here. This
// editor previously offered 3 values while ManualEntityForm offered 4.

function blankCondition(sequence: number): VizJoinCondition {
  return { left_table: '', right_table: '', join_type: 'INNER', condition: '', sequence };
}

export function JoinGraphEditor({ conditions, onChange, readOnly = false }: JoinGraphEditorProps) {
  function updateRow(index: number, patch: Partial<VizJoinCondition>) {
    const next = conditions.map((c, i) => (i === index ? { ...c, ...patch } : c));
    onChange(next);
  }

  function removeRow(index: number) {
    onChange(conditions.filter((_, i) => i !== index));
  }

  function addRow() {
    onChange([...conditions, blankCondition(conditions.length + 1)]);
  }

  if (readOnly) {
    return (
      <div className="flex flex-col gap-2">
        {conditions.length === 0 ? (
          <p className="text-xs text-gray-400 italic px-2 py-2">
            No join conditions defined.
          </p>
        ) : (
          conditions.map((cond, i) => (
            <div
              key={i}
              className="grid gap-2 p-2 bg-gray-50 border border-gray-200 rounded text-xs items-center"
              style={{ gridTemplateColumns: '1fr auto 1fr 2fr' }}
            >
              <span className="font-mono text-gray-700 truncate" title={cond.left_table}>
                {cond.left_table || '—'}
              </span>
              <span className="font-mono text-[10px] text-gray-500 uppercase">
                {cond.join_type || 'INNER'}
              </span>
              <span className="font-mono text-gray-700 truncate" title={cond.right_table}>
                {cond.right_table || '—'}
              </span>
              <span className="font-mono text-gray-600 truncate" title={cond.condition}>
                ON {cond.condition || '—'}
              </span>
            </div>
          ))
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {conditions.map((cond, i) => (
        <div
          key={i}
          className="grid gap-1 p-2 bg-gray-50 border border-gray-200 rounded text-xs"
          style={{ gridTemplateColumns: '1fr 1fr auto 1fr auto' }}
        >
          {/* left_table */}
          <input
            type="text"
            value={cond.left_table}
            onChange={(e) => updateRow(i, { left_table: e.target.value })}
            placeholder="left table"
            className="border border-gray-300 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white font-mono"
          />

          {/* join_type */}
          <select
            value={cond.join_type}
            onChange={(e) => updateRow(i, { join_type: e.target.value })}
            className="border border-gray-300 rounded px-1 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
          >
            {JOIN_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          {/* right_table */}
          <input
            type="text"
            value={cond.right_table}
            onChange={(e) => updateRow(i, { right_table: e.target.value })}
            placeholder="right table"
            className="border border-gray-300 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white font-mono"
          />

          {/* condition */}
          <input
            type="text"
            value={cond.condition}
            onChange={(e) => updateRow(i, { condition: e.target.value })}
            placeholder="e.g. A.ID = B.AID"
            className="border border-gray-300 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white font-mono col-span-1"
            style={{ gridColumn: '4 / 5' }}
          />

          {/* delete */}
          <button
            onClick={() => removeRow(i)}
            className="text-gray-400 hover:text-red-500 text-base leading-none px-1"
            aria-label="Remove join condition"
            title="Remove"
          >
            ×
          </button>
        </div>
      ))}

      <button
        onClick={addRow}
        className="self-start text-xs text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2 py-1 hover:bg-blue-50 transition-colors"
      >
        + Add join condition
      </button>
    </div>
  );
}
