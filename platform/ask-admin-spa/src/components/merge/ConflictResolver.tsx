import { useMergeStore } from '../../store/mergeStore';
import type { ConflictBlock } from '../../api/types';

const CONFLICT_LABEL: Record<string, string> = {
  field_removed: 'SAP removed this field from its schema',
  field_type_changed: 'SAP changed the data type of this field',
  field_modified: 'SAP sent updated values for this field',
};

function ValueTable({
  values,
  highlightKeys,
}: {
  values: Record<string, unknown>;
  highlightKeys?: string[];
}) {
  const entries = Object.entries(values);
  if (entries.length === 0) {
    return <p className="text-xs text-gray-400 italic">(none)</p>;
  }
  return (
    <table className="w-full text-xs border-collapse">
      <tbody>
        {entries.map(([k, v]) => {
          const isEnriched = highlightKeys?.includes(k);
          return (
            <tr key={k} className={isEnriched ? 'bg-amber-50' : ''}>
              <td
                className={`py-0.5 pr-2 font-mono font-medium align-top whitespace-nowrap ${
                  isEnriched ? 'text-amber-700' : 'text-gray-500'
                }`}
              >
                {k}
              </td>
              <td className="py-0.5 text-gray-800 break-all">{String(v ?? '')}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

interface Props {
  conflict: ConflictBlock;
}

export function ConflictResolver({ conflict }: Props) {
  const { resolve, resolving, resolveError } = useMergeStore();

  const label = CONFLICT_LABEL[conflict.conflict_type] ?? conflict.conflict_type;

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-auto">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Conflict — <span className="font-mono normal-case">{conflict.field_name}</span>
        </span>
        <p className="text-sm text-gray-700">{label}</p>
        {conflict.resolved && (
          <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-0.5 w-fit">
            Resolved: {conflict.resolution ?? '—'}
          </span>
        )}
      </div>

      {/* 3-column comparison */}
      <div className="grid grid-cols-[1fr_auto_1fr] gap-4">
        {/* Your version */}
        <div className="flex flex-col gap-1.5">
          <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
            Your version
          </div>
          <div className="border border-gray-200 rounded p-2 bg-white">
            <ValueTable
              values={conflict.current_value}
              highlightKeys={conflict.enriched_properties}
            />
          </div>
          {conflict.enriched_properties.length > 0 && (
            <p className="text-[10px] text-amber-600">
              Amber = enriched properties:{' '}
              {conflict.enriched_properties.join(', ')}
            </p>
          )}
        </div>

        {/* vs divider */}
        <div className="flex items-center justify-center">
          <span className="text-xs text-gray-400 font-medium">vs</span>
        </div>

        {/* SAP version */}
        <div className="flex flex-col gap-1.5">
          <div className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
            SAP version
          </div>
          <div className="border border-gray-200 rounded p-2 bg-white">
            <ValueTable values={conflict.sap_value} />
          </div>
        </div>
      </div>

      {/* Action row */}
      {!conflict.resolved && (
        <div className="flex gap-3 mt-2">
          <button
            onClick={() => void resolve(conflict.yaml_id, conflict.id, 'keep_enriched')}
            disabled={resolving}
            className="flex-1 text-xs font-medium border-2 border-blue-500 text-blue-700 rounded px-3 py-2 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {resolving && (
              <span className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            )}
            Keep yours — preserve enrichments
          </button>
          <button
            onClick={() => void resolve(conflict.yaml_id, conflict.id, 'accept_sap')}
            disabled={resolving}
            className="flex-1 text-xs font-medium border-2 border-orange-400 text-orange-700 rounded px-3 py-2 hover:bg-orange-50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {resolving && (
              <span className="w-3 h-3 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
            )}
            Accept SAP update
          </button>
        </div>
      )}

      {resolveError && (
        <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5">
          {resolveError}
        </div>
      )}
    </div>
  );
}
