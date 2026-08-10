import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles } from 'lucide-react';
import { MenuDropdown } from '../ui/MenuDropdown';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../ui/alert-dialog';
import { useGraphStore } from '../../store/graphStore';
import { useEditorStore } from '../../store/editorStore';
import {
  getDiffWithLastPublish,
  getYaml,
  publishEntityToEnv,
  unpublishEntityFromEnv,
} from '../../api/client';
import type { DiffWithLastPublishResult } from '../../api/client';
import type { VizField, YAMLNode } from '../../api/types';
import {
  invalidateLifecycle,
  useDataProductLifecycle,
} from '../../hooks/queries/catalogQueries';
import { EnrichEntityDialog } from '../enrichment/EnrichEntityDialog';
import { StatusPill } from '../lifecycle/StatusPill';
import { DeploymentPanel } from '../lifecycle/DeploymentPanel';

interface DetailPanelProps {
  onEdit?: () => void;
  /**
   * Domain-canvas (§03) context. When `onRemoveFromDomain` is provided, the
   * inspector shows a "Remove from this domain" action (membership-only — never
   * deletes the YAML or unpublishes). `domainName` is used only for the tooltip.
   */
  domainName?: string;
  onRemoveFromDomain?: () => void | Promise<void>;
}

export function DetailPanel({ onEdit, domainName, onRemoveFromDomain }: DetailPanelProps) {
  const { selectedNode, selectNode, setFocus, focusNodeId } = useGraphStore();
  const { startEdit }                = useEditorStore();
  const navigate                     = useNavigate();
  const [publishMsg, setPublishMsg]  = useState<string | null>(null);
  const [diffLoading, setDiffLoading] = useState<'dev' | 'prod' | null>(null);
  const [diffEnv, setDiffEnv] = useState<'dev' | 'prod' | null>(null);
  const [diffResult, setDiffResult] = useState<DiffWithLastPublishResult | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [enrichOpen, setEnrichOpen] = useState(false);
  const replaceNode = useGraphStore((s) => s.replaceNode);
  const [publishingEnv, setPublishingEnv] = useState<'dev' | 'prod' | null>(null);
  const [confirmEnv, setConfirmEnv] = useState<'dev' | 'prod' | null>(null);
  const selectedId = selectedNode?.id ?? null;

  // Lifecycle (status + per-env versions) from the shared query cache, so any
  // mutation that calls invalidateLifecycle() (publish, edit, enrich, resolve,
  // restore, add/remove) re-renders this panel automatically. null = not tracked.
  const { data: lifecycle } = useDataProductLifecycle(selectedId);

  if (!selectedNode) return null;

  // How many Business Domains reuse this entity — drives the global-edit
  // guardrail copy (an edit to the shared YAML affects every one of them).
  const domainCount = lifecycle?.business_domain_ids?.length ?? 0;

  // Refresh the selected node after a successful enrichment apply so the
  // panel + downstream Edit panel see the new values without a manual reload.
  async function refreshSelected() {
    if (!selectedNode) return;
    // Enrich-apply commits a change (status → In Review): refresh the shared
    // lifecycle cache so the status pill + canvas chip + catalog row update too.
    invalidateLifecycle();
    try {
      const fresh = await getYaml(selectedNode.id);
      replaceNode(fresh);
    } catch {
      /* non-fatal — the next manual selection will fetch */
    }
  }

  const isFocused = focusNodeId === selectedNode.id;

  async function handleDiffWithLastPublish(env: 'dev' | 'prod') {
    if (!selectedNode) return;
    setDiffLoading(env);
    setDiffEnv(env);
    setDiffError(null);
    setDiffResult(null);
    try {
      const r = await getDiffWithLastPublish(selectedNode.id, env);
      setDiffResult(r);
    } catch (err) {
      setDiffError(err instanceof Error ? err.message : 'Could not load diff');
    } finally {
      setDiffLoading(null);
    }
  }

  // Iter 4 — per-environment publish (dev / prod) via the DeploymentPanel.
  // Atomic env publish: ask-*-{env} index + file-by-file git checkout onto the
  // env branch + lifecycle. Prod is gated server-side (409 before any dev publish).
  async function handlePublishEnv(env: 'dev' | 'prod') {
    if (!selectedNode) return;
    // Capture the entity at click time; the user may switch selection while the
    // publish is in flight, so guard every post-await setState against the LIVE
    // selection (read from the store) to avoid writing entity A's state into B.
    const entityId = selectedNode.id;
    const stillSelected = () => useGraphStore.getState().selectedNode?.id === entityId;
    setPublishingEnv(env);
    setPublishMsg(null);
    try {
      const r = await publishEntityToEnv(entityId, env);
      const warn = r.cascade_warnings.length ? `\n⚠ ${r.cascade_warnings.join('; ')}` : '';
      const sha = r.committed_sha ? ` @${r.committed_sha.slice(0, 7)}` : '';
      // One shared cache → refresh this panel's chips AND the canvas summary,
      // the catalog rows, the history chips — every lifecycle subscriber.
      invalidateLifecycle();
      if (stillSelected()) {
        setPublishMsg(
          `Published to ${env}${sha}  ${r.entities_indexed}e · ${r.fields_indexed}f${warn}`,
        );
      }
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string };
      if (stillSelected()) {
        setPublishMsg(ax.response?.data?.detail ?? ax.message ?? `Publish to ${env} failed`);
      }
    } finally {
      // publishingEnv is panel-global UI state — always clear it, even if the
      // user switched away (otherwise the new entity's buttons stay disabled).
      setPublishingEnv(null);
    }
  }

  // Inverse of publish — physically remove this entity from an env so it stops
  // being answerable when the chat targets that env (it stays in dev/working).
  async function handleUnpublishEnv(env: 'dev' | 'prod') {
    if (!selectedNode) return;
    const entityId = selectedNode.id;
    const name = selectedNode.name ?? entityId;
    if (
      !window.confirm(
        `Unpublish "${name}" from ${env}?\n\nIt will no longer be answerable when the ` +
          `chat targets ${env}. It stays in dev/working and can be re-published.`,
      )
    ) {
      return;
    }
    const stillSelected = () => useGraphStore.getState().selectedNode?.id === entityId;
    setPublishingEnv(env);
    setPublishMsg(null);
    try {
      const r = await unpublishEntityFromEnv(entityId, env);
      const sha = r.committed_sha ? ` @${r.committed_sha.slice(0, 7)}` : '';
      invalidateLifecycle();
      if (stillSelected()) {
        setPublishMsg(`Unpublished from ${env}${sha}  −${r.entities_removed}e · −${r.fields_removed}f`);
      }
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string };
      if (stillSelected()) {
        setPublishMsg(ax.response?.data?.detail ?? ax.message ?? `Unpublish from ${env} failed`);
      }
    } finally {
      setPublishingEnv(null);
    }
  }

  const layerColors: Record<string, string> = {
    bronze: 'bg-blue-100 text-blue-700',
    silver: 'bg-gray-100 text-gray-700',
    gold:   'bg-yellow-100 text-yellow-700',
  };

  function handleEdit() {
    startEdit(selectedNode as YAMLNode);
    onEdit?.();
  }

  return (
    <aside className="w-96 shrink-0 bg-white border-l border-gray-200 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 flex flex-col gap-3">
        {/* Title row: badges + name on left, close × on right */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${layerColors[selectedNode.layer]}`}>
                {selectedNode.layer}
              </span>
              {selectedNode.module && (
                <span className="text-[10px] bg-blue-50 text-blue-600 border border-blue-200 px-1.5 py-0.5 rounded font-medium uppercase">
                  {selectedNode.module}
                </span>
              )}
              {lifecycle && <StatusPill status={lifecycle.status} />}
            </div>
            <h2 className="text-sm font-semibold text-gray-900 truncate">{selectedNode.name}</h2>
            {selectedNode.alias && (
              <p className="text-xs text-gray-500 truncate">alias: {selectedNode.alias}</p>
            )}
          </div>
          <button
            onClick={() => selectNode(null)}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none shrink-0"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Actions row: wraps when the panel is narrow */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {/* Primary: edit the entity. Version/diff actions live on the
              Environments panel below (per-env); rare actions go in ⋯. */}
          {onEdit && (
            <button
              onClick={handleEdit}
              className="text-xs border border-gray-300 rounded px-2 py-0.5 text-gray-600 hover:bg-gray-50 hover:border-gray-400 transition-colors"
              aria-label="Edit node"
              title={
                domainCount > 1
                  ? `Editing is GLOBAL — this entity is reused in ${domainCount} domains; changes affect all of them.`
                  : 'Edit this entity (global — changes affect every domain that reuses it).'
              }
            >
              {onRemoveFromDomain ? 'Edit (global)' : 'Edit'}
            </button>
          )}
          {domainCount > 1 && (
            <span
              className="text-[10px] bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 rounded"
              title={`Reused in ${domainCount} domains — edits here are global.`}
            >
              reused ×{domainCount}
            </span>
          )}
          <button
            onClick={() => setEnrichOpen(true)}
            className="flex items-center gap-1 text-xs rounded px-2 py-0.5 border border-blue-300 text-blue-700 hover:bg-blue-50 transition-colors"
            title={
              selectedNode.layer === 'bronze'
                ? 'AI-assisted enrichment of descriptions + synonyms. Bronze tables are raw SAP fields — the agent benefits more from enriching the Silver / Gold that consume them.'
                : 'AI-assisted enrichment of descriptions + synonyms'
            }
            aria-label="Edit with AI Assist"
          >
            <Sparkles size={11} />
            <span>AI Assist</span>
          </button>
          <button
            onClick={() => setFocus(isFocused ? null : selectedNode.id)}
            className={`text-xs rounded px-2 py-0.5 transition-colors border ${
              isFocused
                ? 'bg-violet-600 text-white border-violet-600 hover:bg-violet-700'
                : 'border-violet-300 text-violet-700 hover:bg-violet-50'
            }`}
            aria-label={isFocused ? 'Exit lineage focus' : 'Focus lineage'}
            title="Isolate this entity's lineage (ancestors + descendants)"
          >
            {isFocused ? 'Exit focus' : 'Lineage'}
          </button>
          {onRemoveFromDomain && (
            <MenuDropdown
              align="right"
              title="More actions"
              items={[
                {
                  label: `Remove from ${domainName ?? 'domain'}`,
                  tone: 'danger',
                  onClick: () => void onRemoveFromDomain(),
                },
              ]}
            />
          )}
        </div>
      </div>

      {enrichOpen && (
        <EnrichEntityDialog
          open
          entity={selectedNode}
          onClose={() => setEnrichOpen(false)}
          onApplied={() => void refreshSelected()}
        />
      )}

      {/* Diff modal — opened from the Environments panel's per-env ⋯ menu */}
      {(diffLoading || diffResult || diffError) && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-lg shadow-xl border border-gray-200 w-full max-w-3xl max-h-[80vh] flex flex-col">
            <div className="flex items-start justify-between p-4 border-b border-gray-200">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-gray-900">
                  Diff vs {diffEnv ?? 'publish'} — {selectedNode.name}
                </h3>
                {diffResult?.last_publish_sha && (
                  <p className="text-[11px] text-gray-500 font-mono mt-0.5">
                    {diffEnv} publish: {diffResult.last_publish_sha.slice(0, 7)} → HEAD (workspace)
                  </p>
                )}
              </div>
              <button
                onClick={() => { setDiffResult(null); setDiffError(null); }}
                className="text-gray-400 hover:text-gray-600 text-xl leading-none ml-3"
                aria-label="Close diff"
              >
                ×
              </button>
            </div>
            <div className="overflow-y-auto flex-1 p-4">
              {diffLoading ? (
                <div className="flex items-center gap-2 text-xs text-gray-500 py-2">
                  <span className="w-4 h-4 border-2 border-gray-300 border-t-transparent rounded-full animate-spin" />
                  Computing diff vs {diffLoading}…
                </div>
              ) : diffError ? (
                <p className="text-xs text-red-600">{diffError}</p>
              ) : diffResult?.last_publish_sha === null ? (
                <p className="text-xs text-gray-500">
                  This entity has never been published to{' '}
                  <span className="font-semibold">{diffEnv}</span> — there is nothing to
                  compare against yet. Publish it to {diffEnv} from the Deployment panel first.
                </p>
              ) : diffResult?.unified_diff ? (
                <pre className="text-[11px] font-mono text-gray-800 whitespace-pre-wrap break-all">
                  {diffResult.unified_diff}
                </pre>
              ) : (
                <p className="text-xs text-green-700">
                  No changes since the {diffEnv} publish — the workspace matches {diffEnv}.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Body — scrollable */}
      <div className="overflow-y-auto flex-1 p-4 flex flex-col gap-4">
        {publishMsg && (
          <div className="text-[11px] rounded px-2 py-1 bg-emerald-50 border border-emerald-200 text-emerald-700 break-words whitespace-pre-wrap">
            {publishMsg}
          </div>
        )}

        {/* Deployment & Versions (UX_CHANGES §6 / CH-4) — per-DP dev/prod publish
            with the gate. Shown once the DP is lifecycle-tracked. */}
        {lifecycle && (
          <DeploymentPanel
            lifecycle={lifecycle}
            publishing={publishingEnv}
            onPublish={(env) => setConfirmEnv(env)}
            onHistory={() => navigate(`/history?yaml=${encodeURIComponent(selectedNode.id)}`)}
            onDiff={(env) => void handleDiffWithLastPublish(env)}
            onUnpublish={(env) => void handleUnpublishEnv(env)}
          />
        )}

        {selectedNode.description && (
          <p className="text-xs text-gray-600 leading-relaxed">{selectedNode.description}</p>
        )}

        {/* Metadata */}
        <Section title="Info">
          <KV label="ID" value={selectedNode.id} mono />
          <KV label="File" value={selectedNode.file_path} mono />
          {selectedNode.composed_of?.length > 0 && (
            <KV label="Sources" value={selectedNode.composed_of.join(', ')} />
          )}
        </Section>

        {/* Join graph */}
        {selectedNode.join_graph?.length > 0 && (
          <Section title={`Join conditions (${selectedNode.join_graph.length})`}>
            <div className="flex flex-col gap-1">
              {selectedNode.join_graph.map((j, i) => (
                <div key={i} className="text-[10px] bg-gray-50 border border-gray-200 rounded p-1.5">
                  <span className="font-medium text-gray-700">{j.left_table}</span>
                  <span className="text-gray-400 mx-1">{j.join_type}</span>
                  <span className="font-medium text-gray-700">{j.right_table}</span>
                  <div className="text-gray-400 font-mono mt-0.5 break-all">{j.condition}</div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Fields */}
        <Section title={`Fields (${selectedNode.fields.length})`}>
          <FieldTable fields={selectedNode.fields} />
        </Section>
      </div>

      {/* Per-DataProduct publish confirmation (always confirm before mutating an env) */}
      <AlertDialog
        open={confirmEnv !== null}
        onOpenChange={(o) => {
          if (!o) setConfirmEnv(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Publish to {confirmEnv ?? ''}?</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmEnv === 'prod'
                ? `Promotes the dev version of "${selectedNode.name}" to prod.`
                : `Deploys the working version of "${selectedNode.name}" to dev.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className={confirmEnv === 'prod' ? 'bg-emerald-600 hover:bg-emerald-700' : undefined}
              onClick={() => {
                const env = confirmEnv;
                setConfirmEnv(null);
                if (env) void handlePublishEnv(env);
              }}
            >
              Publish to {confirmEnv ?? ''}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
        {title}
      </h3>
      {children}
    </div>
  );
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="text-gray-500 shrink-0">{label}:</span>
      <span className={`text-gray-800 break-all ${mono ? 'font-mono text-[10px]' : ''}`}>
        {value}
      </span>
    </div>
  );
}

function FieldTable({ fields }: { fields: VizField[] }) {
  if (fields.length === 0) return <p className="text-xs text-gray-400">No fields</p>;

  const roleColor: Record<string, string> = {
    measure:    'bg-purple-50 text-purple-700',
    dimension:  'bg-teal-50 text-teal-700',
    identifier: 'bg-orange-50 text-orange-700',
    timestamp:  'bg-red-50 text-red-700',
  };

  return (
    <div className="flex flex-col divide-y divide-gray-100">
      {fields.map((f) => (
        <div key={f.name} className="py-1.5 flex flex-col gap-0.5">
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-xs font-mono font-medium text-gray-800">{f.name}</span>
            {f.alias && <span className="text-[10px] text-gray-400">({f.alias})</span>}
            {f.field_role && (
              <span className={`text-[9px] px-1 rounded font-medium ${roleColor[f.field_role] ?? 'bg-gray-100 text-gray-600'}`}>
                {f.field_role}
              </span>
            )}
            {f.key_field && (
              <span className="text-[9px] bg-amber-50 text-amber-700 px-1 rounded font-medium">
                KEY
              </span>
            )}
          </div>
          <div className="flex gap-2 text-[10px] text-gray-500">
            {f.type && <span>{f.type}</span>}
            {f.source && <span className="font-mono">{f.source}</span>}
            {f.aggregation_behavior && <span className="font-medium">{f.aggregation_behavior}</span>}
            {/* Axis 2 — without it the reader cannot tell an additive SUM from a
                SUM that is only valid once a dimension has been collapsed. */}
            {f.additivity === 'semi_additive' && (
              <span
                className="font-medium text-amber-700"
                title="Collapse the listed dimensions first (one row per grain group: the latest row when the dimension is temporal, any one row when a join merely repeats the value), then aggregate across the rest."
              >
                semi-additive over {(f.non_additive_over ?? []).join(', ')}
              </span>
            )}
            {f.additivity === 'non_additive' && (
              <span className="font-medium text-amber-700" title="Never aggregate this measure.">
                non-additive
              </span>
            )}
          </div>
          {f.description && (
            <p className="text-[10px] text-gray-400 leading-tight">{f.description}</p>
          )}
        </div>
      ))}
    </div>
  );
}
