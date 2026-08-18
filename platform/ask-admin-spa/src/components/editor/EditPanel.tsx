/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useState } from 'react';
import { HelpCircle } from 'lucide-react';
import { useEditorStore } from '../../store/editorStore';
import { useAuthStore } from '../../store/authStore';
import { useTranslation } from '../../hooks/useTranslation';
import { FieldEditor } from './FieldEditor';
import { JoinGraphEditor } from './JoinGraphEditor';
import { RelationshipsEditor } from './RelationshipsEditor';
import { CLASSIFICATIONS, ENTITY_ROLES } from '../../lib/semanticConstants';
// TODO(normalization): re-import NormalizationEditor when the parked
// block in the JSX returns.
// import { NormalizationEditor } from './NormalizationEditor';

interface EditPanelProps {
  onClose(): void;
}

const LAYER_COLORS: Record<string, string> = {
  bronze: 'bg-blue-100 text-blue-700',
  silver: 'bg-gray-100 text-gray-700',
  gold:   'bg-yellow-100 text-yellow-700',
};

// Standards §4.1 / §5.1. classification = nature of the source data; at SILVER it
// DRIVES entity_role (C→reference, M→dimension, T→fact|dimension) but is a distinct
// axis, and entity_role is read-only there (recomputed server-side on save). At GOLD
// entity_role is AUTHORED and classification is not offered at all.
// CLASSIFICATIONS / ENTITY_ROLES come from lib/semanticConstants — do not redeclare
// them here; two copies of a vocabulary is how the M/T/C fork started.

export function EditPanel({ onClose }: EditPanelProps) {
  const {
    editBuffer,
    originalNode,
    isDirty,
    isSaving,
    saveError,
    updateNodeProp,
    updateJoinGraph,
    updateRelationships,
    // Structural edits (edit-in-full): add/remove/edit columns. composed_of +
    // grain.entity_grain are no longer hand-edited — they're auto-derived
    // (composed_of via the create-time bronze picker; grain from identifier
    // fields) and recomputed server-side on save.
    addField,
    removeFieldAt,
    updateFieldAt,
    // TODO(normalization): re-import updateNormalization when the
    // Normalization block in the JSX returns.
    cancelEdit,
    save,
  } = useEditorStore();

  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const [fieldSearch, setFieldSearch] = useState('');

  if (!editBuffer || !originalNode) return null;

  const node = editBuffer;
  const showSilverGold = node.layer === 'silver' || node.layer === 'gold';

  // Derived (read-only) fields — mirror the backend, which recomputes these on
  // every save (the client is never authoritative). Shown live so the panel
  // reflects what WILL be persisted.
  //  · entity_role (§5.1, SILVER ONLY): classification + item-level / has-measure.
  //    GOLD authors it — the derivation keys off SAP artefacts that do not exist
  //    at Gold, so the backend no longer recomputes it there.
  //  · grain.entity_grain (Silver): the field_role: identifier names. Gold's
  //    grain is its authored aggregation grain (no identifier fields) — show as
  //    stored, not recomputed.
  const isGold = node.layer === 'gold';
  const hasMeasure = node.fields.some((f) => f.field_role === 'measure');
  const isItem = (node.name ?? '').toLowerCase().includes('item');
  const cls = (node.classification ?? '').toUpperCase();
  const derivedEntityRole =
    cls === 'C'
      ? 'reference'
      : cls === 'M'
        ? 'dimension'
        : cls === 'T'
          ? isItem || hasMeasure
            ? 'fact'
            : 'dimension'
          : 'dimension';
  const derivedGrain =
    node.layer === 'silver'
      ? node.fields.filter((f) => f.field_role === 'identifier').map((f) => f.name).filter(Boolean)
      : node.grain?.entity_grain ?? [];
  //  · the grain dimensions a measure may declare in `non_additive_over`. v2
  //    (2026-08-03) allows ANY grain dimension, not only timestamps: a value that
  //    ACCUMULATES along an ordered dimension needs the latest row, but a value a
  //    join merely REPEATS carries the same value on every row of the group, so any
  //    one of them is exact. Filtered to members that resolve to a real field, since
  //    the model rejects a dimension the grain does not publish.
  const grainDimensions = derivedGrain.filter((g) =>
    node.fields.some((f) => f.name === g),
  );

  const filteredFields = fieldSearch.trim()
    ? node.fields.filter(
        (f) =>
          f.name.toLowerCase().includes(fieldSearch.toLowerCase()) ||
          (f.alias ?? '').toLowerCase().includes(fieldSearch.toLowerCase()),
      )
    : node.fields;

  function handleCancel() {
    cancelEdit();
    onClose();
  }

  function handleSave() {
    save(() => onClose());
  }

  const canSave = isDirty && !isSaving;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      {/* Backdrop click intentionally does NOT close — avoids losing edits.
          Close only via the × button or Cancel. */}
      <div className="bg-white rounded-lg shadow-xl w-full max-w-5xl max-h-[90vh] flex flex-col">

        {/* ── Header ── */}
        <div className="flex items-start justify-between px-5 py-3 border-b border-gray-200 gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${LAYER_COLORS[node.layer]}`}>
                {node.layer}
              </span>
              {showSilverGold && (
                <span className="text-[10px] bg-indigo-50 text-indigo-700 border border-indigo-200 px-1.5 py-0.5 rounded font-medium">
                  {derivedEntityRole}
                </span>
              )}
              {isDirty && (
                <span className="text-[10px] bg-orange-50 text-orange-600 border border-orange-200 px-1.5 py-0.5 rounded font-medium">
                  {t('ep_unsaved')}
                </span>
              )}
            </div>
            <h2 className="text-base font-semibold text-gray-900 truncate">{node.name}</h2>
            <p className="text-[11px] text-gray-400 font-mono truncate">{node.id}</p>
          </div>
          <button
            onClick={handleCancel}
            className="ml-2 text-gray-400 hover:text-gray-600 text-2xl leading-none shrink-0"
            aria-label="Close editor"
          >
            ×
          </button>
        </div>

        {/* ── Body ── */}
        <div className="overflow-y-auto flex-1 px-5 py-4 flex flex-col gap-5">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Left — read-only context (from SAP / ingestion). Silver/Gold only:
                a bronze entity IS a raw SAP table, so it has no grain / composed_of. */}
            {showSilverGold && (
              <div className="lg:col-span-1">
                <SectionTitle hint="Auto-derived structural context (read-only). grain.entity_grain (Silver) = the fields whose role is identifier; composed_of (Silver) = the physical Bronze tables, set via the bronze picker on create. Recomputed on save — never hand-edited (Standards §4.2, marked S).">
                  {t('ep_context')} <span className="ml-1 text-[9px] font-normal normal-case text-amber-600">auto</span>
                </SectionTitle>
                <div className="rounded border border-gray-200 bg-gray-50 p-3 flex flex-col gap-2">
                  <DerivedKV
                    label={node.layer === 'silver' ? 'grain.entity_grain' : 'grain.entity_grain (aggregation)'}
                    value={derivedGrain.length ? derivedGrain.join(', ') : null}
                    empty={node.layer === 'silver' ? 'set a field role = identifier' : '—'}
                  />
                  {node.layer === 'silver' && (
                    <DerivedKV
                      label="composed_of"
                      value={(node.composed_of ?? []).length ? (node.composed_of ?? []).join(', ') : null}
                      empty="—"
                    />
                  )}
                  <DerivedKV label="business_grain" value={node.grain?.business_grain ?? null} empty="—" />
                </div>
              </div>
            )}

            {/* Right — editable entity-level (full width for bronze, which has no
                read-only context column). */}
            <div className={`flex flex-col gap-4 ${showSilverGold ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
              <IdentityBanner email={user?.email ?? null} />

              <div>
                <SectionTitle hint="What it is + its grain + when to use it. Signal, not filler — see standards §11.">
                  {t('ep_section_description')}
                </SectionTitle>
                <textarea
                  value={node.description ?? ''}
                  onChange={(e) => updateNodeProp('description', e.target.value || null)}
                  rows={4}
                  placeholder={t('ep_description_ph')}
                  className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-y"
                />
              </div>

              {showSilverGold && (
                <div>
                  <SectionTitle hint="The SAP module that OWNS this entity, UPPERCASE (SD, MM, PP). Required — it also decides the workspace path, so a blank value fails to save. A Gold spanning modules may carry a list; that list is not editable here yet, so avoid saving a multi-module Gold from this panel.">
                    {t('ep_section_module')}
                  </SectionTitle>
                  <input
                    type="text"
                    value={Array.isArray(node.module) ? node.module.join(', ') : node.module ?? ''}
                    onChange={(e) => updateNodeProp('module', e.target.value || null)}
                    readOnly={Array.isArray(node.module)}
                    title={
                      Array.isArray(node.module)
                        ? 'Multi-module entity — read-only here, because saving through this field would collapse the list to a single value.'
                        : undefined
                    }
                    placeholder={t('ep_module_ph')}
                    className={`w-full text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                      Array.isArray(node.module) ? 'bg-gray-100 text-gray-600' : ''
                    }`}
                  />
                </div>
              )}

              {/* Classification & physical table (standards §4.1/§4.2/§5.1).
                  Silver/Gold ONLY: a bronze entity IS a raw SAP table, so it has
                  no db_table_name, classification or entity_role. */}
              {showSilverGold && (
                <div>
                  <SectionTitle
                    hint={
                      isGold
                        ? "Physical table + how it's used in SQL. At GOLD, entity_role is AUTHORED (default fact) — the §5.1 derivation keys off SAP artefacts a Gold does not have. classification has no Data-Modeler source at Gold and drives nothing, so it is not offered here."
                        : "Physical table + how it's used in SQL. classification (M/T/C, nature of the data) DRIVES entity_role (fact/dimension/reference) per standards §5.1 — C→reference, M→dimension, T→fact|dimension — so entity_role is auto-derived, not editable. Set classification to steer it."
                    }
                  >
                    {t('ep_classification')}
                  </SectionTitle>
                  <div className={`grid gap-2 ${isGold ? 'grid-cols-2' : 'grid-cols-3'}`}>
                    <label className="flex flex-col gap-1">
                      <span className="text-[10px] text-gray-500 font-mono">db_table_name</span>
                      <input
                        type="text"
                        value={node.db_table_name ?? ''}
                        onChange={(e) => updateNodeProp('db_table_name', e.target.value || null)}
                        placeholder={t('ep_table_ph')}
                        className="w-full text-xs font-mono border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </label>
                    {isGold ? (
                      <label className="flex flex-col gap-1">
                        <span className="text-[10px] text-gray-500 font-mono">entity_role</span>
                        <select
                          value={node.entity_role ?? 'fact'}
                          onChange={(e) => updateNodeProp('entity_role', e.target.value)}
                          title="Authored at Gold. `fact` unless this Gold is a pure dimensional lookup."
                          className="w-full text-xs border border-gray-200 rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
                        >
                          {ENTITY_ROLES.map((r) => (
                            <option key={r} value={r}>{r}</option>
                          ))}
                        </select>
                      </label>
                    ) : (
                      <>
                        <div className="flex flex-col gap-1">
                          <span className="text-[10px] text-gray-500 font-mono flex items-center gap-1">
                            entity_role
                            <span className="text-[8px] font-bold px-1 rounded-full bg-amber-100 border border-amber-200 text-amber-700">auto</span>
                          </span>
                          <div
                            title="Derived from classification (§5.1) — recomputed on save"
                            className="w-full text-xs border border-gray-200 rounded px-2 py-1 bg-gray-100 text-gray-600 font-mono"
                          >
                            {derivedEntityRole}
                          </div>
                        </div>
                        <label className="flex flex-col gap-1">
                          <span className="text-[10px] text-gray-500 font-mono">classification</span>
                          <select
                            value={node.classification ?? ''}
                            onChange={(e) => updateNodeProp('classification', e.target.value || null)}
                            className="w-full text-xs border border-gray-200 rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
                          >
                            <option value="">—</option>
                            {CLASSIFICATIONS.map((c) => (
                              <option key={c.value} value={c.value}>{c.label}</option>
                            ))}
                          </select>
                        </label>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Join graph — Silver only, now EDITABLE. Gold entities are single
              physical tables (no Bronze composition) so the block is hidden.
              join_graph is build/lineage metadata (not a runtime join — the
              agent queries db_table_name); editable so a hand-authored Silver
              can fix its bronze↔bronze joins. For SAP-sourced Silvers an edit
              here surfaces on the next ingest through the normal conflict flow. */}
          {node.layer === 'silver' && (
            <div>
              <SectionTitle hint="How the composed Bronze tables join during assembly (build/lineage — NOT a runtime join). Editable; for SAP-sourced Silvers, re-ingest reconciles via conflicts.">
                {t('ep_join_graph').replace('{n}', String(node.join_graph.length))}
              </SectionTitle>
              <JoinGraphEditor
                conditions={node.join_graph}
                onChange={updateJoinGraph}
              />
            </div>
          )}

          {/* Relationships (Silver/Gold) — full width */}
          {showSilverGold && (
            <div>
              <SectionTitle hint="Lineage edges to other Silvers/Golds — drives the JOIN path-finding. Cost rubric & rules: standards §6-§7.">
                {t('ep_relationships').replace('{n}', String(node.relationships.length))}
              </SectionTitle>
              <RelationshipsEditor
                relationships={node.relationships}
                onChange={updateRelationships}
                thisEntity={node}
              />
            </div>
          )}

          {/* TODO(normalization): hidden 2026-06. The currency / UoM
              normalization block (Standards §4.4) is parked until we agree
              on how it feeds SQL generation end-to-end. The data shape
              (entity.normalization + per-field normalization_flag) is kept
              alive on the wire so re-enabling is JSX-only: render the block
              + the column in FieldEditor again. Field still exists on the
              YAML and on the API model.
          {showSilverGold && (
            <div>
              <SectionTitle hint="Currency / UoM conversion logic for amounts & quantities (deterministic SQL). Standards §4.4.">
                Normalization
              </SectionTitle>
              <NormalizationEditor value={node.normalization} onChange={updateNormalization} />
            </div>
          )}
          */}

          {/* Fields — full width */}
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <SectionTitle hint="Per-column metadata — fully editable: add/remove columns, rename, retype, re-key. Silver/Gold add role / agg / synonyms (+ source on Silver); Bronze is type + key + description. Types + derived roles are normalized on save.">
                {t('ep_fields').replace('{n}', String(node.fields.length))}
              </SectionTitle>
              <input
                type="text"
                value={fieldSearch}
                onChange={(e) => setFieldSearch(e.target.value)}
                placeholder={t('ep_field_search_ph')}
                className="ml-auto flex-1 max-w-xs text-xs border border-gray-200 rounded px-2 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>

            {filteredFields.length === 0 ? (
              <p className="text-xs text-gray-400">{t('ep_no_fields_match').replace('{q}', fieldSearch)}</p>
            ) : (
              <div className="overflow-x-auto border border-gray-200 rounded">
                <table className="w-full text-xs border-collapse">
                  <thead className="bg-gray-50">
                    <tr className="border-b border-gray-200 text-[10px] text-gray-500 font-medium">
                      <th className="text-left py-1.5 px-2">{t('ep_col_name')}</th>
                      <th className="text-left py-1.5 px-2" title="Canonical data type — dimensions in ⚙ Advanced">{t('ep_col_type')}</th>
                      {/* Column order MUST match FieldEditor's cells: Name · Type ·
                          [Alias bronze] · [Source silver] · [Role !bronze] · Description.
                          Less-common props (aggregation, synonyms, type dimensions) live
                          in the per-field ⚙ Advanced expander — same panel as the New
                          form, so the two editors stay at parity. `source` is Silver-only
                          (Gold = {db_table_name}.{name}); `alias` is Bronze-only. */}
                      {node.layer === 'bronze' && (
                        <th className="text-left py-1.5 px-2" title="Field business alias">{t('ep_col_alias')}</th>
                      )}
                      {node.layer === 'silver' && (
                        <th className="text-left py-1.5 px-2" title="Physical TABLE.COLUMN">{t('ep_col_source')}</th>
                      )}
                      {node.layer !== 'bronze' && (
                        <th className="text-left py-1.5 px-2">{t('ep_col_role')}</th>
                      )}
                      <th className="text-left py-1.5 px-2">{t('ep_col_description')}</th>
                      <th className="w-8" />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredFields.map((f) => {
                      // Index into editBuffer.fields (not the filtered view) so
                      // structural ops target the right row. Keyed by index so a
                      // rename doesn't remount the row + drop focus.
                      const idx = node.fields.indexOf(f);
                      return (
                        <FieldEditor
                          key={idx}
                          field={f}
                          index={idx}
                          layer={node.layer}
                          onChange={updateFieldAt}
                          onRemove={removeFieldAt}
                          grainDimensions={grainDimensions}
                        />
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <button
              onClick={addField}
              className="mt-2 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2 py-1 hover:bg-blue-50 transition-colors"
            >
              {t('ep_add_field')}
            </button>
          </div>
        </div>

        {/* ── Footer ── */}
        <div className="border-t border-gray-200 px-5 py-3 flex items-center gap-3">
          {saveError && (
            <p className="flex-1 text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1">
              {saveError}
            </p>
          )}
          <div className="ml-auto flex gap-2">
            <button
              onClick={handleCancel}
              className="text-xs border border-gray-300 rounded px-4 py-1.5 text-gray-600 hover:bg-gray-50 transition-colors"
            >
              {t('common_cancel')}
            </button>
            <button
              onClick={handleSave}
              disabled={!canSave}
              className="flex items-center justify-center gap-2 text-xs bg-blue-600 text-white rounded px-5 py-1.5 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {isSaving && (
                <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
              )}
              {t('ep_save')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

function IdentityBanner({ email }: { email: string | null }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 p-2.5 bg-gray-50 border border-gray-200 rounded">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
        {t('ep_editing_as')}
      </span>
      <span className="text-xs font-medium text-gray-700">{email ?? 'dev session'}</span>
      <span className="ml-auto text-[10px] text-gray-400">{t('ep_commit_author')}</span>
    </div>
  );
}

function SectionTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <h3 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5 flex items-center gap-1">
      {children}
      {hint && (
        <span title={hint} className="text-gray-300 hover:text-gray-500 cursor-help">
          <HelpCircle className="h-3 w-3" />
        </span>
      )}
    </h3>
  );
}

// Read-only display for an auto-derived field. Shows the value mono-spaced, or a
// muted hint when empty (e.g. "set a field role = identifier").
function DerivedKV({
  label,
  value,
  empty = '—',
}: {
  label: string;
  value: string | null | undefined;
  empty?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] text-gray-500 font-mono">{label}</span>
      <span className="text-[11px] text-gray-700 font-mono break-all">
        {value || <span className="text-amber-600">{empty}</span>}
      </span>
    </div>
  );
}
