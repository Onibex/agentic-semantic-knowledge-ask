/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useState } from 'react';
import { useMergeStore } from '../../store/mergeStore';
import type { ConflictDecision } from '../../api/types';
import { ConflictResolver } from './ConflictResolver';

interface Props {
  entityId: string;
  entityName?: string;
  /** Called when the dialog closes. `resolvedAny` is true if at least one
   *  conflict was resolved while it was open, so the caller can refresh. */
  onClose: (resolvedAny: boolean) => void;
}

/**
 * Per-entity conflict resolver, opened from the Semantic Knowledge catalog row
 * (the ⚠ badge). Reuses the merge store + ConflictResolver so the resolution
 * mechanics stay identical to the former ASK Merge page — conflicts are an
 * orthogonal attribute of an entity, resolved where the entity lives.
 *
 * Bulk fast paths: an upload-first ingest can land a whole export's worth of
 * conflicts at once, so per-field clicking does not scale. Each row carries a
 * checkbox; the header bar resolves the SELECTION (or everything when nothing
 * is selected) with one request per decision.
 */
export function ConflictDialog({ entityId, entityName, onClose }: Props) {
  const { conflicts, conflictsLoading, fetchAllConflicts, resolveBulk, resolving } =
    useMergeStore();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    void fetchAllConflicts([entityId]);
  }, [entityId, fetchAllConflicts]);

  const own = conflicts.filter((c) => c.yaml_id === entityId);
  const pending = own.filter((c) => !c.resolved);
  // Resolving drops a conflict from the pending set; once the entity loaded
  // some and now has none, the user has reconciled it.
  const resolvedAny = own.length > 0 && pending.length === 0;

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allChecked = pending.length > 0 && pending.every((c) => selected.has(c.id));
  const toggleAll = () =>
    setSelected(allChecked ? new Set() : new Set(pending.map((c) => c.id)));

  // Bulk target: the checked subset, or every pending conflict when none is
  // checked — "Accept all SAP" with an empty selection means exactly that.
  const targets = pending.filter((c) => selected.size === 0 || selected.has(c.id));
  const bulk = async (decision: ConflictDecision) => {
    await resolveBulk(
      entityId,
      targets.map((c) => ({ conflict_id: c.id, decision })),
    );
    setSelected(new Set());
  };
  const scopeLabel = selected.size > 0 ? `${targets.length} selected` : `all ${pending.length}`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg border border-gray-200 bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-gray-200 p-4">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-gray-900">
              Resolve conflicts — {entityName ?? entityId}
            </h3>
            <p className="mt-0.5 text-[11px] text-gray-500">
              SAP changed fields you curated. Decide per field, or use the bulk
              actions below on a selection (nothing selected = everything).
            </p>
          </div>
          <button
            onClick={() => onClose(resolvedAny)}
            className="ml-3 text-xl leading-none text-gray-400 hover:text-gray-600"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {pending.length > 1 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 bg-gray-50 px-4 py-2">
            <label className="flex items-center gap-1.5 text-xs text-gray-600">
              <input type="checkbox" checked={allChecked} onChange={toggleAll} />
              Select all ({pending.length})
            </label>
            <div className="ml-auto flex gap-2">
              <button
                onClick={() => void bulk('keep_enriched')}
                disabled={resolving || targets.length === 0}
                className="rounded border-2 border-blue-500 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Keep mine — {scopeLabel}
              </button>
              <button
                onClick={() => void bulk('accept_sap')}
                disabled={resolving || targets.length === 0}
                className="rounded border-2 border-orange-400 px-2.5 py-1 text-xs font-medium text-orange-700 hover:bg-orange-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Accept SAP — {scopeLabel}
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 divide-y divide-gray-100 overflow-y-auto">
          {conflictsLoading ? (
            <div className="p-6 text-center text-xs text-gray-400">Loading conflicts…</div>
          ) : pending.length === 0 ? (
            <div className="p-6 text-center text-sm text-green-700">
              ✓ No pending conflicts — this entity is reconciled.
            </div>
          ) : (
            pending.map((c) => (
              <ConflictResolver
                key={c.id}
                conflict={c}
                selected={selected.has(c.id)}
                onToggleSelect={pending.length > 1 ? () => toggle(c.id) : undefined}
              />
            ))
          )}
        </div>

        <div className="border-t border-gray-200 p-3 text-right">
          <button
            onClick={() => onClose(resolvedAny)}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-700"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
