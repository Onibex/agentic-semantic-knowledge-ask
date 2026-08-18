/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

﻿import { useCallback, useEffect, useState } from 'react';
import { FileUp, LayoutGrid, Loader2, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from '../hooks/useTranslation';
import { YAMLGraph } from '../components/graph/YAMLGraph';
import { FilterPanel } from '../components/panels/FilterPanel';
import { DetailPanel } from '../components/panels/DetailPanel';
import { EditPanel } from '../components/editor/EditPanel';
import { UploadYamlDialog } from '../components/workspaces/UploadYamlDialog';
import { useGraphStore } from '../store/graphStore';
import { useEditorStore } from '../store/editorStore';
import { useWorkspaceStore } from '../store/workspaceStore';
import { usePublishedStore } from '../store/publishedStore';
import { indexWorkspace, listYamls } from '../api/client';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../components/ui/alert-dialog';

export function GraphPage() {
  const { t } = useTranslation();
  const { fetchAll, reset, loading, error, rawNodes, selectedNode, setSearch, clearSearch, searchQuery, searchResults, focusNodeId, setFocus } = useGraphStore();
  const focusNode = focusNodeId ? rawNodes.find((n) => n.id === focusNodeId) ?? null : null;
  const { editingNodeId } = useEditorStore();

  // Active workspace drives the catalogue scope. The page blocks rendering of
  // the graph until one is selected — consistent with the chat side, which
  // refuses to send a question without `workspace_id`.
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const availableWorkspaces = useWorkspaceStore((s) => s.available);
  const workspacesLoading = useWorkspaceStore((s) => s.loading);
  const activeWorkspace = useWorkspaceStore((s) => s.active());

  const [mode, setMode] = useState<'view' | 'edit'>('view');
  const [localSearch, setLocalSearch] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [publishToast, setPublishToast] = useState<{ msg: string; isError: boolean } | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [confirmPublishOpen, setConfirmPublishOpen] = useState(false);

  // System-level YAML count, independent of the active workspace's DP scope.
  // Used to distinguish two empty states:
  //   * systemYamlCount === 0 → no YAMLs on disk at all → first-run UX.
  //   * systemYamlCount > 0   → files exist but the workspace doesn't
  //                              reference them → existing "manage workspace" UX.
  // null = not yet loaded (suppresses both empty branches to avoid flicker).
  const [systemYamlCount, setSystemYamlCount] = useState<number | null>(null);

  const refreshSystemCount = useCallback(async () => {
    try {
      const all = await listYamls();
      setSystemYamlCount(all.length);
    } catch {
      // Network errors here are non-fatal — the page still renders the
      // legacy empty state. We just lose the first-run hint.
      setSystemYamlCount(null);
    }
  }, []);

  // Published-ids set drives the Published/Unpublished chip + the Unpublish action.
  const refreshPublished = usePublishedStore((s) => s.refresh);

  async function handleBulkPublish() {
    if (publishing) return;
    setConfirmPublishOpen(false);
    setPublishing(true);
    setPublishToast(null);
    try {
      const r = await indexWorkspace();
      // Build a sentence that reads like a sentence — the old abbreviations
      // ("12e · 80f · 14j") looked like compiler output. Be explicit so a
      // non-engineer can read the toast and know what landed.
      const summary = [
        `${r.entities_indexed} ${r.entities_indexed === 1 ? 'entity' : 'entities'}`,
        `${r.fields_indexed} ${r.fields_indexed === 1 ? 'field' : 'fields'}`,
        `${r.edges_indexed} join ${r.edges_indexed === 1 ? 'edge' : 'edges'}`,
      ].join(', ');
      const lead =
        r.failed > 0
          ? `Published ${r.indexed} of ${r.total} (${r.failed} failed)`
          : `Published ${r.indexed} of ${r.total}`;
      setPublishToast({
        msg: `${lead} — indexed ${summary}.`,
        isError: r.failed > 0,
      });
      void refreshPublished();
    } catch (err) {
      setPublishToast({
        msg: err instanceof Error ? err.message : 'Publish failed',
        isError: true,
      });
    } finally {
      setPublishing(false);
    }
  }

  // Refetch the catalogue whenever the active workspace changes. We reset
  // first so the UI doesn't briefly show stale nodes from the previous
  // workspace while the new request is in flight.
  useEffect(() => {
    if (!activeWorkspaceId) {
      reset();
      return;
    }
    reset();
    void fetchAll(activeWorkspaceId);
  }, [activeWorkspaceId, fetchAll, reset]);

  // Load the published-ids set once on mount. Refreshed implicitly after
  // every Publish / Unpublish via the side panel + after a successful
  // bulk Publish here.
  useEffect(() => {
    void refreshPublished();
  }, [refreshPublished]);

  // Mount-time fetch of the system-wide YAML count so the first-run empty
  // state can offer the Upload button without depending on a workspace
  // being configured.
  useEffect(() => {
    void refreshSystemCount();
  }, [refreshSystemCount]);

  // If the selected node changes (or is cleared), drop back to view mode
  useEffect(() => {
    if (!selectedNode) setMode('view');
  }, [selectedNode]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (localSearch.trim()) {
        setSearch(localSearch.trim());
      } else {
        clearSearch();
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [localSearch, setSearch, clearSearch]);

  // ── Empty states (block the graph) ──────────────────────────────────────
  // Computed as JSX into `bodyContent` so the UploadYamlDialog can be
  // mounted by a SINGLE return below — otherwise early-returning empty
  // states left the dialog out of the tree and Upload-button clicks
  // would set `uploadOpen=true` without rendering the dialog.
  let bodyContent: React.ReactNode | null = null;

  if (!activeWorkspaceId && !workspacesLoading) {
    bodyContent = (
      <div className="flex h-full items-center justify-center bg-gray-50">
        <div className="max-w-md text-center px-6">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-600 mb-4">
            <LayoutGrid className="h-6 w-6" />
          </div>
          {availableWorkspaces.length === 0 ? (
            <>
              <h2 className="text-lg font-semibold text-gray-900 mb-1">
                {t('graph_no_ws_title')}
              </h2>
              <p className="text-sm text-gray-600 mb-4">
                {t('graph_no_ws_desc')}
              </p>
              <Link
                to="/workspaces"
                className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
              >
                {t('graph_create_ws_btn')}
              </Link>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-gray-900 mb-1">
                {t('graph_pick_ws_title')}
              </h2>
              <p className="text-sm text-gray-600">
                {t('graph_pick_ws_desc')}
              </p>
            </>
          )}
        </div>
      </div>
    );
  } else if (activeWorkspace && !loading && rawNodes.length === 0 && !error) {
    // Three sub-states share this branch — the difference is whether ANY
    // YAML exists on disk yet. `null` means the count is still loading;
    // suppress both empty messages to avoid flicker.
    if (systemYamlCount === null) {
      bodyContent = (
        <div className="flex h-full items-center justify-center bg-gray-50">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      );
    } else if (systemYamlCount === 0) {
      // First-run: nothing in the semantic-layer repo. Manage-workspace
      // can't help — there's nothing to pick. Lead the admin to Upload.
      bodyContent = (
        <div className="flex h-full items-center justify-center bg-gray-50">
          <div className="max-w-md text-center px-6">
            <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-600 mb-4">
              <FileUp className="h-6 w-6" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900 mb-1">
              {t('graph_empty_layer_title')}
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              {t('graph_empty_layer_desc')}
            </p>
            <button
              onClick={() => setUploadOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
            >
              <FileUp className="h-4 w-4" />
              {t('graph_upload_yaml_btn')}
            </button>
            <p className="mt-4 text-xs text-gray-500">
              Already have files in <code className="px-1 bg-gray-100 rounded">REPO_ROOT</code>?
              Restart <code className="px-1 bg-gray-100 rounded">ask-admin-api</code> or run
              <code className="px-1 bg-gray-100 rounded ml-1">ask-kg ingest-dir</code> /
              <code className="px-1 bg-gray-100 rounded ml-1">POST /v1/admin/yaml/index-workspace</code>.
            </p>
          </div>
        </div>
      );
    } else {
      // Files exist on disk, but the active workspace doesn't reference any —
      // fall back to the "configure your workspace" empty state, but expose
      // Upload too in case the admin wants to add more files.
      bodyContent = (
        <div className="flex h-full items-center justify-center bg-gray-50">
          <div className="max-w-md text-center px-6">
            <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-amber-50 text-amber-600 mb-4">
              <LayoutGrid className="h-6 w-6" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900 mb-1">
              {t('graph_ws_no_entities_title').replace('{name}', activeWorkspace.name || activeWorkspace.slug)}
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              {t('graph_ws_no_entities_desc').replace('{n}', String(systemYamlCount))}
            </p>
            <div className="flex items-center justify-center gap-2">
              <Link
                to={`/workspaces/${activeWorkspace.slug}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-blue-300 bg-white px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-50"
              >
                {t('graph_manage_ws_btn')}
              </Link>
              <button
                onClick={() => setUploadOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <FileUp className="h-3.5 w-3.5" />
                {t('graph_upload_more_btn')}
              </button>
            </div>
          </div>
        </div>
      );
    }
  }

  if (bodyContent !== null) {
    return (
      <>
        {bodyContent}
        {uploadOpen && (
          <UploadYamlDialog
            open
            onClose={() => setUploadOpen(false)}
            onUploaded={() => {
              if (activeWorkspaceId) {
                void fetchAll(activeWorkspaceId);
              } else {
                void fetchAll();
              }
              void refreshSystemCount();
            }}
          />
        )}
      </>
    );
  }

  return (
    <>
    <div className="flex h-full overflow-hidden">
      <FilterPanel />

      <div className="flex-1 relative overflow-hidden">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
            <div className="flex flex-col items-center gap-2">
              <div className="w-8 h-8 border-4 border-blue-400 border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-gray-500">{t('graph_loading')}</span>
            </div>
          </div>
        )}
        {error && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-2 rounded shadow">
            {error}
          </div>
        )}
        {/* Empty workspace case is rendered as a full-page empty state above —
            this branch only fires if the fetch returned zero rows for a workspace
            that the resolver thought had entities. Keep the message terse. */}

        {/* Focus-mode banner */}
        {focusNode && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 bg-violet-600 text-white text-xs font-medium rounded-full pl-3 pr-1.5 py-1 shadow">
            <span className="opacity-90">{t('graph_lineage_of')}</span>
            <span className="font-semibold">{focusNode.name}</span>
            <button
              onClick={() => setFocus(null)}
              className="ml-1 rounded-full bg-white/20 hover:bg-white/30 px-2 py-0.5 transition-colors"
            >
              {t('graph_exit')}
            </button>
          </div>
        )}

        {/* Top toolbar: search + bulk Publish */}
        <div className="absolute top-3 left-3 right-3 z-10 flex items-center gap-2">
          <input
            type="search"
            placeholder={t('graph_search_ph')}
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
            className="w-48 text-sm border border-gray-300 rounded-md px-3 py-1.5 bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
          {searchQuery && (
            <span className="text-xs text-gray-500 bg-white px-2 py-1 rounded border border-gray-200 shadow-sm">
              {t('graph_n_found').replace('{n}', String(searchResults.size))}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {publishToast && (
              <span
                className={`text-[11px] px-2 py-1 rounded shadow-sm border ${
                  publishToast.isError
                    ? 'bg-red-50 border-red-200 text-red-700'
                    : 'bg-emerald-50 border-emerald-200 text-emerald-700'
                }`}
              >
                {publishToast.msg}
              </span>
            )}
            <button
              onClick={() => setUploadOpen(true)}
              className="inline-flex items-center gap-1.5 text-xs font-medium rounded-md border border-blue-300 bg-white text-blue-700 hover:bg-blue-50 px-3 py-1.5 shadow-sm transition-colors"
              title="Upload one or more YAML files to the workspace (does NOT publish to the runtime index)."
            >
              <FileUp className="h-3.5 w-3.5" />
              {t('graph_upload_yaml_btn')}
            </button>
            <button
              onClick={() => setConfirmPublishOpen(true)}
              disabled={publishing}
              className="inline-flex items-center gap-1.5 text-xs font-medium rounded-md border border-emerald-300 bg-white text-emerald-700 hover:bg-emerald-50 disabled:opacity-60 px-3 py-1.5 shadow-sm transition-colors"
              title="Publish every workspace YAML into the runtime index. Per-entity Publish lives in the side panel."
            >
              {publishing ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t('graph_publishing')}
                </>
              ) : (
                <>
                  <Upload className="h-3.5 w-3.5" />
                  {t('graph_publish_ws_btn')}
                </>
              )}
            </button>
          </div>
        </div>

        <YAMLGraph />
      </div>

      {/* Right-side panel: edit mode takes priority over detail view */}
      {mode === 'edit' && editingNodeId ? (
        <EditPanel onClose={() => setMode('view')} />
      ) : (
        selectedNode && (
          <DetailPanel onEdit={() => setMode('edit')} />
        )
      )}

      {uploadOpen && (
        <UploadYamlDialog
          open
          onClose={() => setUploadOpen(false)}
          onUploaded={() => {
            // Refresh the catalogue so the newly-uploaded files show up in the graph.
            if (activeWorkspaceId) {
              void fetchAll(activeWorkspaceId);
            } else {
              void fetchAll();
            }
            // Also bump the system-wide count so the first-run empty state
            // hands off to the workspace empty state on the next render
            // (instead of staying frozen at "Your semantic layer is empty").
            void refreshSystemCount();
          }}
        />
      )}
    </div>
    <BulkPublishConfirm
      open={confirmPublishOpen}
      onOpenChange={setConfirmPublishOpen}
      onConfirm={() => void handleBulkPublish()}
    />
    </>
  );
}

interface BulkPublishConfirmProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

function BulkPublishConfirm({ open, onOpenChange, onConfirm }: BulkPublishConfirmProps) {
  const { t } = useTranslation();
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Upload className="h-4 w-4 text-emerald-600" />
            {t('graph_publish_confirm_title')}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t('graph_publish_confirm_desc1')}
            <br />
            <br />
            {t('graph_publish_confirm_desc2')}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('common_cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            {t('graph_publish_ws_btn')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
