import { useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import type { YAMLLayer, YAMLNode } from '../../api/types';
import { useGraphStore } from '../../store/graphStore';
import { useTranslation } from '../../hooks/useTranslation';

const LAYERS: { id: YAMLLayer; color: string }[] = [
  { id: 'gold',   color: 'text-yellow-600' },
  { id: 'silver', color: 'text-gray-600' },
  { id: 'bronze', color: 'text-blue-600' },
];

const ROLE_IDS: { id: string; badge: string }[] = [
  { id: 'fact',      badge: 'bg-indigo-100 text-indigo-700' },
  { id: 'dimension', badge: 'bg-teal-100 text-teal-700' },
  { id: 'reference', badge: 'bg-gray-100 text-gray-600' },
];

const ROLE_BADGE: Record<string, string> = {
  fact: 'bg-indigo-100 text-indigo-700',
  dimension: 'bg-teal-100 text-teal-700',
  reference: 'bg-gray-100 text-gray-600',
};

export function FilterPanel() {
  return (
    <aside className="w-56 shrink-0 bg-white border-r border-gray-200 overflow-y-auto p-4 flex flex-col gap-5">
      <FilterPanelBody />
    </aside>
  );
}

/**
 * The rail content without its own container — extracted so the Domain Canvas
 * (§03) can host it under a Filters | Knowledge toggle while GraphPage keeps
 * using <FilterPanel /> (the aside-wrapped variant) unchanged.
 */
export function FilterPanelBody() {
  const { t } = useTranslation()
  const {
    filters,
    allModules,
    toggleLayer,
    toggleModule,
    toggleRole,
    toggleEntity,
    resetView,
    visibleIds,
    refCounts,
    rawNodes,
    focusNodeId,
    selectNode,
  } = useGraphStore();

  const roleLabels: Record<string, string> = {
    fact: t('fp_role_fact'),
    dimension: t('fp_role_dimension'),
    reference: t('fp_role_reference'),
  }
  const layerLabels: Record<string, string> = { gold: 'Gold', silver: 'Silver', bronze: 'Bronze' }

  // Entities with at least one unresolved conflict — surfaced so the curator
  // can jump straight from the sidebar to the SAP Updates merge UI.
  const pendingConflicts = rawNodes.filter((n: YAMLNode) =>
    Array.isArray(n.meta?.conflicts) &&
    n.meta!.conflicts.some((c) => {
      const conflict = c as { resolved?: boolean };
      return !conflict.resolved;
    }),
  );

  const [expanded, setExpanded] = useState<Set<YAMLLayer>>(new Set());

  const toggleExpanded = (layer: YAMLLayer) => {
    const next = new Set(expanded);
    if (next.has(layer)) next.delete(layer);
    else next.add(layer);
    setExpanded(next);
  };

  const entitiesByLayer = (layer: YAMLLayer) =>
    rawNodes
      .filter((n) => n.layer === layer)
      .sort(
        (a, b) =>
          (refCounts[b.id] ?? 0) - (refCounts[a.id] ?? 0) || a.name.localeCompare(b.name),
      );

  return (
    <>
      {focusNodeId && (
        <div className="text-[10px] text-violet-700 bg-violet-50 border border-violet-200 rounded px-2 py-1.5 leading-snug">
          {t('fp_focus_active')}
        </div>
      )}

      {/* Pending conflicts inbox */}
      {pendingConflicts.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-700 mb-2 flex items-center gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5" />
            {t('fp_pending_conflicts')}
            <span className="ml-auto text-[10px] font-bold bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded-full">
              {pendingConflicts.length}
            </span>
          </h3>
          <div className="flex flex-col gap-0.5 max-h-40 overflow-y-auto pr-1">
            {pendingConflicts.map((n) => {
              const unresolved = (n.meta?.conflicts ?? []).filter(
                (c) => !(c as { resolved?: boolean }).resolved,
              ).length;
              return (
                <button
                  key={n.id}
                  onClick={() => selectNode(n.id)}
                  className="flex items-center gap-1.5 px-1.5 py-1 text-left text-xs rounded hover:bg-amber-50 group"
                  title={`${n.id} — ${unresolved} unresolved`}
                >
                  <span className="truncate text-gray-700 group-hover:text-amber-900 flex-1">
                    {n.name}
                  </span>
                  <span className="text-[10px] tabular-nums bg-amber-100 text-amber-800 px-1 rounded">
                    {unresolved}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* View preset */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">{t('fp_view')}</h3>
        <div className="flex gap-1">
          <button
            onClick={() => resetView('main')}
            className="flex-1 text-xs rounded border border-gray-300 px-2 py-1 text-gray-700 hover:bg-gray-50"
            title="Golds + Silver facts only (transactional flow)"
          >
            {t('fp_main_flow')}
          </button>
          <button
            onClick={() => resetView('all')}
            className="flex-1 text-xs rounded border border-gray-300 px-2 py-1 text-gray-700 hover:bg-gray-50"
            title="Show everything (all layers and roles)"
          >
            {t('fp_view_all')}
          </button>
        </div>
      </div>

      {/* Roles */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
          {t('fp_roles')}
        </h3>
        <div className="flex flex-col gap-1">
          {ROLE_IDS.map((r) => (
            <label key={r.id} className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={filters.roles.has(r.id)}
                onChange={() => toggleRole(r.id)}
                className="rounded"
              />
              <span className={`text-[11px] px-1.5 py-0.5 rounded font-medium ${r.badge}`}>
                {roleLabels[r.id]}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Layers + per-entity tree */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">{t('fp_layers')}</h3>
        <div className="flex flex-col gap-0.5">
          {LAYERS.map((l) => {
            const entities = entitiesByLayer(l.id);
            const isOpen = expanded.has(l.id);
            return (
              <div key={l.id}>
                <div className="flex items-center gap-1.5 py-0.5">
                  <button
                    onClick={() => toggleExpanded(l.id)}
                    className="text-gray-400 hover:text-gray-600 shrink-0 disabled:opacity-30"
                    aria-label={isOpen ? 'Collapse' : 'Expand'}
                    disabled={entities.length === 0}
                  >
                    {isOpen ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <label className="flex items-center gap-2 cursor-pointer select-none flex-1 min-w-0">
                    <input
                      type="checkbox"
                      checked={filters.layers.has(l.id)}
                      onChange={() => toggleLayer(l.id)}
                      className="rounded"
                    />
                    <span className={`text-sm font-medium ${l.color}`}>{layerLabels[l.id]}</span>
                    <span className="ml-auto text-xs text-gray-400">{entities.length}</span>
                  </label>
                </div>

                {isOpen && entities.length > 0 && (
                  <div className="ml-5 mt-0.5 mb-1 flex flex-col gap-0.5 border-l border-gray-100 pl-2">
                    {entities.map((n) => {
                      const refs = refCounts[n.id] ?? 0;
                      const role = (n.entity_role as string) ?? '';
                      return (
                        <label
                          key={n.id}
                          className="flex items-center gap-1.5 cursor-pointer select-none group"
                          title={`${n.id}${refs ? ` — ${refs} reference(s)` : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={visibleIds.has(n.id)}
                            onChange={() => toggleEntity(n.id)}
                            className="rounded scale-90"
                          />
                          <span className="text-xs text-gray-600 truncate group-hover:text-gray-900">
                            {n.name}
                          </span>
                          {role && l.id !== 'bronze' && (
                            <span
                              className={`text-[9px] px-1 rounded ${ROLE_BADGE[role] ?? 'bg-gray-100 text-gray-500'}`}
                            >
                              {role[0].toUpperCase()}
                            </span>
                          )}
                          {refs > 0 && (
                            <span
                              className={`ml-auto text-[10px] tabular-nums px-1 rounded ${
                                refs >= 4 ? 'bg-amber-100 text-amber-700' : 'text-gray-400'
                              }`}
                            >
                              {refs}
                            </span>
                          )}
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <p className="mt-1.5 text-[10px] text-gray-400 leading-snug">
          {t('fp_layers_hint')}
        </p>
      </div>

      {allModules.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
            {t('fp_modules')}
          </h3>
          <div className="flex flex-col gap-1">
            {allModules.map((m) => (
              <label key={m} className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={!filters.modules.has(m)}
                  onChange={() => toggleModule(m)}
                  className="rounded"
                />
                <span className="text-sm text-gray-700 uppercase">{m}</span>
                <span className="ml-auto text-xs text-gray-400">
                  {rawNodes.filter((n) => n.module === m).length}
                </span>
              </label>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
