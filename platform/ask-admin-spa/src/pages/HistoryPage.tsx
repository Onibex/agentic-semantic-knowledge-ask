/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { History } from 'lucide-react';
import { useHistoryStore } from '../store/historyStore';
import { CommitTimeline } from '../components/history/CommitTimeline';
import { SimpleDiffViewer } from '../components/history/SimpleDiffViewer';
import { MonacoDiffViewer } from '../components/editor/MonacoDiffViewer';
import { RestoreDialog } from '../components/history/RestoreDialog';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/lifecycle/StatusPill';
import { listYamls } from '../api/client';
import type { HistoryBranch, YAMLNodeSummary } from '../api/types';
import { useDataProductLifecycle } from '../hooks/queries/catalogQueries';
import { useTranslation } from '../hooks/useTranslation';

// UX_CHANGES audit §4.4 — three history tabs (labels translated inside component).
const HISTORY_TAB_VALUES: HistoryBranch[] = ['working', 'dev', 'prod'];

const LAYER_DOT: Record<string, string> = {
  bronze: 'bg-blue-400',
  silver: 'bg-gray-400',
  gold: 'bg-yellow-400',
};

export function HistoryPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const {
    selectedYamlId,
    historyBranch,
    commits,
    totalCount,
    loading,
    fromSha,
    toSha,
    diffResult,
    diffLoading,
    restoreDialogOpen,
    selectYaml,
    setHistoryBranch,
    loadMore,
    setFromSha,
    setToSha,
    loadDiff,
    openRestoreDialog,
  } = useHistoryStore();

  const [search, setSearch] = useState('');
  // Shared lifecycle cache — a Restore (historyStore.confirmRestore) invalidates
  // it, so the version chips refresh without re-selecting the entity.
  const { data: lifecycle } = useDataProductLifecycle(selectedYamlId);
  const [allNodes, setAllNodes] = useState<YAMLNodeSummary[]>([]);
  const [nodesLoading, setNodesLoading] = useState(true);

  // The picker is the GLOBAL catalog — fetched independently of the graph store
  // so it never inherits a domain-scoped (partial) node set left by the canvas,
  // and avoids the per-node getYaml storm. Summaries carry id/name/layer.
  useEffect(() => {
    let cancelled = false;
    listYamls()
      .then((nodes) => {
        if (!cancelled) setAllNodes(nodes);
      })
      .catch(() => {
        if (!cancelled) setAllNodes([]);
      })
      .finally(() => {
        if (!cancelled) setNodesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Deep-link entry point: the entity inspector opens /history?yaml=<id>, which
  // lands directly on that entity's timeline instead of the empty picker.
  useEffect(() => {
    const yamlId = params.get('yaml');
    if (yamlId && yamlId !== selectedYamlId) void selectYaml(yamlId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);


  const filteredNodes = allNodes.filter(
    (n) =>
      n.id.toLowerCase().includes(search.toLowerCase()) ||
      (n.name ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  const hasMore = commits.length < totalCount;
  const canDiff = fromSha !== null && toSha !== null && selectedYamlId !== null;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHeader
        title={t('history_title')}
        subtitle={t('history_subtitle')}
        icon={History}
        iconTone="gray"
      />
      <div className="flex flex-1 overflow-hidden">
      {/* Left sidebar: YAML list */}
      <div className="w-56 shrink-0 border-r border-gray-200 bg-gray-50 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-gray-200 shrink-0">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            {t('history_yaml_files')}
          </div>
          <input
            type="text"
            placeholder={t('history_search')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
          />
        </div>
        <div className="flex-1 overflow-y-auto">
          {nodesLoading && allNodes.length === 0 ? (
            <div className="flex items-center justify-center py-6 text-xs text-gray-400 gap-2">
              <span className="w-4 h-4 border-2 border-gray-300 border-t-transparent rounded-full animate-spin" />
              {t('history_loading')}
            </div>
          ) : (
            <>
              {filteredNodes.map((node) => (
                <button
                  key={node.id}
                  onClick={() => void selectYaml(node.id)}
                  className={`w-full text-left px-3 py-2 text-xs border-b border-gray-100 hover:bg-gray-100 transition-colors ${
                    selectedYamlId === node.id
                      ? 'bg-blue-50 text-blue-700 font-medium'
                      : 'text-gray-700'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${LAYER_DOT[node.layer] ?? 'bg-gray-300'}`} />
                    <span className="truncate font-mono">{node.name}</span>
                  </div>
                  <div className="truncate text-[10px] text-gray-400 ml-3">{node.layer}</div>
                </button>
              ))}
              {filteredNodes.length === 0 && (
                <p className="px-3 py-2 text-xs text-gray-400">{t('history_no_results')}</p>
              )}
            </>
          )}
        </div>
      </div>

      {/* Main area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {!selectedYamlId ? (
          <div className="flex flex-1 items-center justify-center text-gray-500">
            <div className="text-center max-w-sm px-6">
              <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 text-gray-500 mb-3">
                <History className="h-6 w-6" />
              </div>
              <p className="text-sm font-medium text-gray-700">
                {t('history_pick_yaml')}
              </p>
              <p className="text-xs mt-1 text-gray-500">
                {t('history_pick_yaml_desc')}
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* Top: header + diff trigger */}
            <div className="shrink-0 border-b border-gray-200 px-4 py-2 flex items-center gap-3 bg-white">
              <span className="text-xs font-semibold text-gray-700 font-mono">
                {selectedYamlId}
              </span>
              <span className="text-xs text-gray-400">{t('history_commits_count').replace('{count}', String(totalCount))}</span>
              {lifecycle && (
                <div className="flex items-center gap-1.5">
                  <StatusPill status={lifecycle.status} />
                  <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold border bg-teal-50 text-teal-700 border-teal-200">
                    working v{lifecycle.version}
                    {lifecycle.status === 'In Review' ? ' · draft' : ''}
                  </span>
                  {lifecycle.dev_published && (
                    <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold border bg-blue-50 text-blue-700 border-blue-200">
                      dev v{lifecycle.dev_published.version}
                    </span>
                  )}
                  {lifecycle.prod_published && (
                    <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold border bg-red-50 text-red-700 border-red-200">
                      prod v{lifecycle.prod_published.version}
                    </span>
                  )}
                </div>
              )}
              {canDiff && (
                <button
                  onClick={() => void loadDiff()}
                  disabled={diffLoading}
                  className="ml-auto text-xs font-medium bg-blue-600 text-white rounded px-2 py-1 hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
                >
                  {diffLoading && (
                    <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  )}
                  {t('history_view_diff')}
                </button>
              )}
              {(fromSha || toSha) && (
                <button
                  onClick={() => {
                    setFromSha(null);
                    setToSha(null);
                  }}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  {t('history_clear_selection')}
                </button>
              )}
            </div>

            {/* History tabs — Working / Deployed to dev / Deployed to prod (§4.4) */}
            <div className="shrink-0 border-b border-gray-200 px-4 bg-white flex items-center gap-1">
              {HISTORY_TAB_VALUES.map((tabValue) => (
                <button
                  key={tabValue}
                  onClick={() => void setHistoryBranch(tabValue)}
                  className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
                    historyBranch === tabValue
                      ? 'border-blue-600 text-blue-700'
                      : 'border-transparent text-gray-500 hover:text-gray-800'
                  }`}
                >
                  {t(`history_tab_${tabValue}` as Parameters<typeof t>[0])}
                </button>
              ))}
              {historyBranch !== 'working' && (
                <span className="ml-auto text-[11px] text-gray-400">
                  {t('history_restoring_note')}
                </span>
              )}
            </div>

            {/* Diff banner */}
            {(fromSha || toSha) && (
              <div className="shrink-0 px-4 py-1.5 bg-gray-50 border-b border-gray-200 flex items-center gap-3 text-xs text-gray-600">
                <span>
                  FROM:{' '}
                  <span className="font-mono font-medium">
                    {fromSha ? fromSha.slice(0, 7) : '—'}
                  </span>
                </span>
                <span className="text-gray-300">→</span>
                <span>
                  TO:{' '}
                  <span className="font-mono font-medium">
                    {toSha ? toSha.slice(0, 7) : '—'}
                  </span>
                </span>
              </div>
            )}

            {/* Split: timeline top, diff bottom */}
            <div className={`flex-1 flex flex-col overflow-hidden ${diffResult ? 'gap-0' : ''}`}>
              {/* Timeline */}
              <div
                className={`overflow-y-auto border-b border-gray-200 ${
                  diffResult ? 'h-1/2' : 'flex-1'
                }`}
              >
                {loading && commits.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-32 text-sm text-gray-500 gap-3">
                    <span className="w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                    <span>{t('history_loading_commits')}</span>
                  </div>
                ) : commits.length === 0 && historyBranch !== 'working' ? (
                  <div className="flex flex-col items-center justify-center h-32 text-center px-6 gap-1">
                    <p className="text-sm font-medium text-gray-600">
                      {t('history_not_deployed').replace('{env}', historyBranch)}
                    </p>
                    <p className="text-xs text-gray-500">
                      {t('history_no_deploy_history').replace(/\{env\}/g, historyBranch)}
                    </p>
                  </div>
                ) : (
                  <CommitTimeline
                    commits={commits}
                    fromSha={fromSha}
                    toSha={toSha}
                    onSelectFrom={setFromSha}
                    onSelectTo={setToSha}
                    onRestore={openRestoreDialog}
                    hasMore={hasMore}
                    onLoadMore={() => void loadMore()}
                  />
                )}
              </div>

              {/* Diff viewer — Monaco side-by-side when both blobs are
                  returned by the API (newer admin-api), unified-diff fallback
                  otherwise. */}
              {diffResult && (
                <div className="h-1/2 overflow-hidden">
                  {diffResult.content_from !== undefined && diffResult.content_to !== undefined ? (
                    <MonacoDiffViewer
                      original={diffResult.content_from}
                      modified={diffResult.content_to}
                      fromSha={diffResult.from_sha}
                      toSha={diffResult.to_sha}
                    />
                  ) : (
                    <SimpleDiffViewer
                      unifiedDiff={diffResult.unified_diff}
                      fromSha={diffResult.from_sha}
                      toSha={diffResult.to_sha}
                    />
                  )}
                </div>
              )}

              {diffLoading && !diffResult && (
                <div className="flex items-center justify-center h-16 text-xs text-gray-400 gap-2 border-t border-gray-200">
                  <span className="w-4 h-4 border-2 border-gray-300 border-t-transparent rounded-full animate-spin" />
                  {t('history_computing_diff')}
                </div>
              )}
            </div>
          </>
        )}
      </div>

      </div>

      {/* Restore dialog overlay */}
      {restoreDialogOpen && <RestoreDialog />}
    </div>
  );
}
