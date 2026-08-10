import { useEffect } from 'react';
import { useMergeStore } from '../../store/mergeStore';
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
 */
export function ConflictDialog({ entityId, entityName, onClose }: Props) {
  const { conflicts, conflictsLoading, fetchAllConflicts } = useMergeStore();

  useEffect(() => {
    void fetchAllConflicts([entityId]);
  }, [entityId, fetchAllConflicts]);

  const own = conflicts.filter((c) => c.yaml_id === entityId);
  const pending = own.filter((c) => !c.resolved);
  // Resolving drops a conflict from the pending set; once the entity loaded
  // some and now has none, the user has reconciled it.
  const resolvedAny = own.length > 0 && pending.length === 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg border border-gray-200 bg-white shadow-xl">
        <div className="flex items-start justify-between border-b border-gray-200 p-4">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-gray-900">
              Resolve conflicts — {entityName ?? entityId}
            </h3>
            <p className="mt-0.5 text-[11px] text-gray-500">
              SAP changed fields you enriched. Decide per field: keep yours or accept SAP.
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

        <div className="flex-1 divide-y divide-gray-100 overflow-y-auto">
          {conflictsLoading ? (
            <div className="p-6 text-center text-xs text-gray-400">Loading conflicts…</div>
          ) : pending.length === 0 ? (
            <div className="p-6 text-center text-sm text-green-700">
              ✓ No pending conflicts — this entity is reconciled.
            </div>
          ) : (
            pending.map((c) => <ConflictResolver key={c.id} conflict={c} />)
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
