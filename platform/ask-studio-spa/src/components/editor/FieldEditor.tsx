/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { memo, useState } from 'react';
import { Trash2 } from 'lucide-react';

import type { VizField, YAMLLayer } from '../../api/types';
import { CanonicalTypeSelect } from './CanonicalTypeEditor';
import { AdvancedToggle, FieldAdvanced } from './FieldAdvanced';

interface FieldEditorProps {
  field: VizField;
  index: number;
  layer: YAMLLayer;
  /** Edit any field prop by row index (supports rename / retype / re-key). */
  onChange(index: number, prop: keyof VizField, value: unknown): void;
  onRemove(index: number): void;
  /** Grain fields whose role is timestamp — the only dimensions a measure may
   *  declare in `non_additive_over` (v1). See REQ_ADDITIVITY_CONTRACT.md. */
  grainDimensions?: string[];
}

// Full role taxonomy (see SEMANTIC_LAYER_STANDARDS.md §5).
const FIELD_ROLES = [
  '',
  'measure',
  'dimension',
  'identifier',
  'timestamp',
  'attribute',
  'status_flag',
] as const;

const ROLE_HINT =
  'Where the column may appear in SQL — measure: aggregate · dimension: group/filter · ' +
  'identifier: key · timestamp: dates · attribute: text (no GROUP BY) · status_flag: filter only';

const cell =
  'w-full text-xs border border-gray-200 rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white min-w-0';

// Fully editable (edit-in-full): name / type / key / alias / source are inline; the
// less-common props (type dimensions, aggregation, synonyms) live in the per-field
// Advanced expander (⚙) — the SAME panel the New form uses, so the two forms match.
export const FieldEditor = memo(function FieldEditor({
  field,
  index,
  layer,
  onChange,
  onRemove,
  grainDimensions,
}: FieldEditorProps) {
  const set = (prop: keyof VizField, value: unknown) => onChange(index, prop, value);
  const [advanced, setAdvanced] = useState(false);

  return (
    <>
      <tr className="border-b border-gray-100 hover:bg-gray-50 group align-middle">
        {/* name + key toggle. The key checkbox is BRONZE-only: a Bronze field's
            key_field drives primary_key. On Silver/Gold there is no key_field —
            a key is expressed as field_role: identifier (the Role select below). */}
        <td className="py-1 pr-2 align-middle">
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={field.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="column_name"
              className={`${cell} font-mono`}
            />
            {layer === 'bronze' && (
              <label
                className="flex items-center gap-0.5 text-[9px] text-gray-500 shrink-0"
                title="Primary key"
              >
                <input
                  type="checkbox"
                  checked={!!field.key_field}
                  onChange={(e) => set('key_field', e.target.checked)}
                />
                key
              </label>
            )}
          </div>
        </td>

        {/* type — inline base + canonical chip; dimensions live in Advanced (⚙) */}
        <td className="py-1 pr-2 align-middle">
          <CanonicalTypeSelect value={field.type ?? ''} onChange={(v) => set('type', v)} />
        </td>

        {/* alias — Bronze only (field business alias) */}
        {layer === 'bronze' && (
          <td className="py-1 pr-2 align-middle">
            <input
              type="text"
              value={field.alias ?? ''}
              onChange={(e) => set('alias', e.target.value || null)}
              placeholder="sales_doc"
              title="Field business alias"
              className={cell}
            />
          </td>
        )}

        {/* source — Silver only (bronze lineage). Gold = {table}.{name} (auto);
            Bronze has no source. */}
        {layer === 'silver' && (
          <td className="py-1 pr-2 align-middle">
            <input
              type="text"
              value={field.source ?? ''}
              onChange={(e) => set('source', e.target.value)}
              placeholder="VBAK.NETWR"
              title="Bronze lineage — TABLE.COLUMN this field reads from"
              className={`${cell} font-mono`}
            />
          </td>
        )}

        {/* field_role — Silver/Gold */}
        {layer !== 'bronze' && (
          <td className="py-1 pr-2 align-middle">
            <select
              value={field.field_role ?? ''}
              onChange={(e) => set('field_role', e.target.value || null)}
              title={ROLE_HINT}
              className={cell}
            >
              {FIELD_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r || '— (auto)'}
                </option>
              ))}
            </select>
          </td>
        )}

        {/* description */}
        <td className="py-1 pr-2 align-middle">
          <input
            type="text"
            value={field.description ?? ''}
            onChange={(e) => set('description', e.target.value || null)}
            placeholder="disambiguate / warn — omit if obvious"
            title="Only add if it changes a decision (disambiguation, hazard, synonyms). See standards §11."
            className={cell}
          />
        </td>

        {/* advanced toggle + remove */}
        <td className="py-1 align-middle">
          <div className="flex items-center gap-1.5">
            <AdvancedToggle open={advanced} onClick={() => setAdvanced((a) => !a)} />
            <button
              onClick={() => onRemove(index)}
              className="text-gray-400 hover:text-red-500"
              aria-label="Remove field"
              title="Remove column"
            >
              <Trash2 size={13} />
            </button>
          </div>
        </td>
      </tr>
      {advanced && (
        <tr className="border-b border-gray-100">
          <td colSpan={99} className="px-2 pb-1.5">
            <FieldAdvanced
              name={field.name}
              layer={layer}
              type={field.type ?? ''}
              onType={(v) => set('type', v)}
              role={field.field_role ?? ''}
              agg={field.aggregation_behavior ?? ''}
              onAgg={(v) => set('aggregation_behavior', v || null)}
              additivity={field.additivity ?? ''}
              onAdditivity={(v) => set('additivity', v || null)}
              nonAdditiveOver={field.non_additive_over ?? []}
              onNonAdditiveOver={(v) => set('non_additive_over', v)}
              grainDimensions={grainDimensions}
              synonyms={field.synonyms ?? []}
              onSynonyms={(v) => set('synonyms', v)}
            />
          </td>
        </tr>
      )}
    </>
  );
});
