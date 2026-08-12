/**
 * Semantic Knowledge — global catalog of every DataProduct (UX_CHANGES audit
 * CH-0 / §04). One row per silver/gold YAML entity, showing its lifecycle
 * status + version + which Business Domains reuse it, plus the entity's own
 * §3.1 header.
 *
 * Data comes from two reads joined client-side by entity_id:
 *   - GET /v1/admin/catalog  → lifecycle (status, version, business domains)
 *   - GET /v1/viz/yamls      → the entity header (name, layer, module,
 *                              business_process, …) + structure counts
 *
 * `business_process` is the only header key with a permanent column — it is the
 * business axis and the catalog had no way to show it. The rest expands per row
 * (`EntityHeaderDetail`), because a column each would win every width fight and
 * it is data you consult one entity at a time. Expanding costs no request: the
 * list projection already carries it.
 *
 * Distinct from the Docs page (`/admin/docs`), which ingests PDF/Markdown into
 * the RAG index — that is NOT the semantic YAML layer.
 */

import { AlertTriangle, ChevronDown, ChevronRight, History as HistoryIcon, Library, Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { deleteKgEntity, getYaml } from '@/api/client'
import type { DataProductStatus, YAMLLayer, YAMLNodeSummary } from '@/api/types'
import { useDataProductCatalog } from '@/hooks/queries/catalogQueries'
import { useYamlList } from '@/hooks/queries/yamlQueries'
import { useEditorStore } from '@/store/editorStore'
import { useGraphStore } from '@/store/graphStore'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { PageHeader } from '@/components/PageHeader'
import { EntityHeaderDetail } from '@/components/catalog/EntityHeaderDetail'
import { EditPanel } from '@/components/editor/EditPanel'
import { StatusPill } from '@/components/lifecycle/StatusPill'
import { ConflictDialog } from '@/components/merge/ConflictDialog'
import { CreateEntityDialog } from '@/components/workspaces/CreateEntityDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { MenuDropdown } from '@/components/ui/MenuDropdown'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useTranslation } from '@/hooks/useTranslation'

type StatusFilter = 'all' | DataProductStatus | 'conflicts'

const VALID_STATUS: StatusFilter[] = ['all', 'In Review', 'Released', 'conflicts']

function parseStatusParam(raw: string | null): StatusFilter {
  return VALID_STATUS.includes(raw as StatusFilter) ? (raw as StatusFilter) : 'all'
}

// Layer order + hue, matching the graph's FilterPanel so a layer means the same
// colour everywhere in the app (bronze is blue there, not amber — one convention).
const LAYERS: YAMLLayer[] = ['bronze', 'silver', 'gold']
const LAYER_STYLE: Record<YAMLLayer, { on: string; off: string }> = {
  bronze: { on: 'bg-blue-600 text-white', off: 'bg-blue-50 text-blue-700 hover:bg-blue-100' },
  silver: { on: 'bg-gray-600 text-white', off: 'bg-gray-100 text-gray-600 hover:bg-gray-200' },
  gold: { on: 'bg-yellow-600 text-white', off: 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100' },
}

/** Remembers the layer selection across sessions. The catalog lists every
 *  lifecycle-tracked entity, and in a real workspace roughly half of them are
 *  Bronze raw tables — so a curator working the Silver/Gold plane needs the
 *  choice to STICK, not to be re-made on every visit. Nothing is removed from the
 *  listing: turning a layer back on is one click. */
const LAYER_PREF_KEY = 'semanticKnowledge_layers'

function parseLayers(raw: string | null): Set<YAMLLayer> | null {
  if (!raw) return null
  const picked = raw
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter((s): s is YAMLLayer => (LAYERS as string[]).includes(s))
  return picked.length ? new Set(picked) : null
}

interface CatalogRow {
  entityId: string
  name: string
  layer: string | null
  module: string | null
  /** Standards §3.1, required at Silver/Gold — the business axis the catalog was
   *  missing. The only header key that earned a permanent place in the table. */
  businessProcess: string | null
  status: DataProductStatus
  version: number
  domainCount: number
  pendingConflicts: number
  /** The full catalog projection, for the expandable header detail. Undefined when
   *  the lifecycle index knows an entity whose YAML is not in the workspace — such
   *  a row still lists (with its status) but has nothing to expand. */
  yaml: YAMLNodeSummary | undefined
}

export default function SemanticKnowledgePage() {
  const { t } = useTranslation()

  // Shared lifecycle + entity-metadata caches. Any mutation that calls
  // invalidateLifecycle() (publish, edit, enrich, conflict resolve, restore,
  // add/remove from domain) re-renders these rows automatically.
  const {
    data: lifecycle = [],
    isLoading: lcLoading,
    isError,
    refetch: refetchCatalog,
  } = useDataProductCatalog()
  const { data: yamls = [], isLoading: yamlsLoading, refetch: refetchYamls } = useYamlList()
  const loading = lcLoading || yamlsLoading
  const reload = () => {
    void refetchCatalog()
    void refetchYamls()
  }
  const [params] = useSearchParams()
  const [filter, setFilter] = useState('')
  // Honor ?status= deep-links (CH-6 post-import lands on In Review; the Health
  // page's "Resolve →" lands on conflicts).
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() =>
    parseStatusParam(params.get('status')),
  )
  // Layers shown. `?layer=silver,gold` deep-links (same idiom as ?status=), else
  // the remembered choice, else everything — nothing is hidden by default.
  const [layerFilter, setLayerFilter] = useState<Set<YAMLLayer>>(
    () =>
      parseLayers(params.get('layer')) ??
      parseLayers(localStorage.getItem(LAYER_PREF_KEY)) ??
      new Set(LAYERS),
  )
  const toggleLayer = (layer: YAMLLayer) =>
    setLayerFilter((s) => {
      const next = new Set(s)
      if (next.has(layer)) next.delete(layer)
      else next.add(layer)
      localStorage.setItem(LAYER_PREF_KEY, [...next].join(','))
      return next
    })
  const [createOpen, setCreateOpen] = useState(false)
  const [conflictEntity, setConflictEntity] = useState<{ id: string; name: string } | null>(null)
  // Which rows show their header detail. Same expander idiom as the field editors.
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggleExpanded = (entityId: string) =>
    setExpanded((s) => {
      const next = new Set(s)
      if (next.has(entityId)) next.delete(entityId)
      else next.add(entityId)
      return next
    })

  // Per-row actions: Edit (reuse the global EditPanel), History, Delete.
  const navigate = useNavigate()
  const editingNodeId = useEditorStore((s) => s.editingNodeId)
  const startEdit = useEditorStore((s) => s.startEdit)
  const cancelEdit = useEditorStore((s) => s.cancelEdit)
  const [opening, setOpening] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<CatalogRow | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleEdit(entityId: string) {
    setOpening(entityId)
    try {
      // The EditPanel's relationship editor reads the full catalog from the
      // graph store for its target field pickers — make sure it's loaded
      // (idempotent; no-op if already populated). SCOPED to the active
      // workspace: the scoped branch is ONE request (listScopedYamls), while
      // the unscoped legacy branch is listYamls + N x getYaml — a 35-request
      // storm that took minutes on a bind-mounted workspace (Windows Docker).
      const activeWorkspaceId = useWorkspaceStore.getState().activeWorkspaceId
      await useGraphStore.getState().ensureLoaded(activeWorkspaceId)
      const node = await getYaml(entityId)
      startEdit(node)
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string }
      toast.error(ax.response?.data?.detail ?? ax.message ?? 'Could not open the editor')
    } finally {
      setOpening(null)
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteKgEntity(deleteTarget.entityId)
      toast.success(t('sk_toast_deleted').replace('{name}', deleteTarget.name))
      setDeleteTarget(null)
      reload()
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string }
      toast.error(ax.response?.data?.detail ?? ax.message ?? 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  const rows = useMemo<CatalogRow[]>(() => {
    const yamlById = new Map(yamls.map((y) => [y.id, y]))
    return lifecycle
      .map((lc) => {
        const y = yamlById.get(lc.entity_id)
        return {
          entityId: lc.entity_id,
          name: y?.name ?? lc.entity_id,
          layer: y?.layer ?? null,
          module: y?.module ?? null,
          businessProcess: y?.business_process ?? null,
          status: lc.status,
          version: lc.version,
          domainCount: lc.business_domain_ids.length,
          pendingConflicts: lc.pending_conflicts ?? 0,
          yaml: y,
        }
      })
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [lifecycle, yamls])

  // Conflicts are an orthogonal axis (not a status): count entities that carry
  // at least one unresolved SAP-merge conflict, for the filter pill + badges.
  const conflictedCount = useMemo(
    () => rows.reduce((n, r) => n + (r.pendingConflicts > 0 ? 1 : 0), 0),
    [rows],
  )

  const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: t('sk_filter_all') },
    { value: 'In Review', label: t('sk_filter_in_review') },
    { value: 'Released', label: t('sk_filter_released') },
  ]

  // How many rows each layer contributes, for the pill counts. Computed over the
  // UNFILTERED rows so a count never changes as you toggle the pills.
  const layerCounts = useMemo(() => {
    const counts = new Map<YAMLLayer, number>(LAYERS.map((l) => [l, 0]))
    for (const r of rows) {
      if (r.layer && counts.has(r.layer as YAMLLayer)) {
        counts.set(r.layer as YAMLLayer, (counts.get(r.layer as YAMLLayer) ?? 0) + 1)
      }
    }
    return counts
  }, [rows])

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return rows.filter((r) => {
      // A row whose YAML is missing from the workspace has no layer to filter on;
      // hiding it would make an entity that needs attention the hardest to find.
      if (r.layer && !layerFilter.has(r.layer as YAMLLayer)) return false
      if (statusFilter === 'conflicts') {
        if (r.pendingConflicts === 0) return false
      } else if (statusFilter !== 'all' && r.status !== statusFilter) {
        return false
      }
      if (!q) return true
      // Searches the header too, not just id / name / module: "what is the entity
      // that reads GOLD_INVENTORY_SITUATION" and "everything in ORDER TO CASH" are
      // the two questions a catalog is actually asked.
      return [
        r.entityId,
        r.name,
        r.module,
        r.businessProcess,
        r.yaml?.description,
        r.yaml?.db_table_name,
        r.yaml?.alias,
        r.yaml?.tag1,
        r.yaml?.tag2,
      ]
        .filter(Boolean)
        .some((v) => (v as string).toLowerCase().includes(q))
    })
  }, [rows, filter, statusFilter, layerFilter])

  return (
    <div className="flex flex-col h-full">
      <PageHeader
        title={t('sk_title')}
        subtitle={t('sk_subtitle')}
        icon={Library}
        iconTone="violet"
        right={
          <div className="flex items-center gap-3">
            <button
              onClick={reload}
              className="inline-flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-900"
              title={t('sk_refresh')}
            >
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
              {t('sk_refresh')}
            </button>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus size={14} />
              <span className="ml-1.5">{t('sk_new_data_product')}</span>
            </Button>
          </div>
        }
      />

      <CreateEntityDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          // Post-import: land in the review queue (audit CH-6).
          setStatusFilter('In Review')
          reload()
        }}
      />

      <div className="flex-1 overflow-auto p-4">
        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <div className="relative flex-1 min-w-[14rem] max-w-md">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t('sk_filter_placeholder')}
              className="pl-8"
            />
          </div>

          {/* Layer toggles — independent, so "Silver + Gold" is one click away.
              A dimmed pill means that layer is hidden, never that it is gone. */}
          <div className="flex items-center gap-1">
            <span className="mr-0.5 text-[10px] uppercase tracking-wider text-gray-400">
              {t('sk_filter_layers')}
            </span>
            {LAYERS.map((l) => {
              const on = layerFilter.has(l)
              return (
                <button
                  key={l}
                  onClick={() => toggleLayer(l)}
                  aria-pressed={on}
                  title={t(on ? 'sk_filter_layer_hide' : 'sk_filter_layer_show').replace('{layer}', l)}
                  className={`rounded-md px-2 py-1 text-xs font-medium capitalize transition-colors ${
                    on ? LAYER_STYLE[l].on : `${LAYER_STYLE[l].off} opacity-60`
                  }`}
                >
                  {l}
                  <span className="ml-1 tabular-nums opacity-70">{layerCounts.get(l) ?? 0}</span>
                </button>
              )
            })}
          </div>

          <span className="h-5 w-px bg-gray-200" aria-hidden />

          <div className="flex items-center gap-1">
            {STATUS_FILTERS.map((s) => (
              <button
                key={s.value}
                onClick={() => setStatusFilter(s.value)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  statusFilter === s.value
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {s.label}
              </button>
            ))}
            {conflictedCount > 0 && (
              <button
                onClick={() => setStatusFilter('conflicts')}
                className={`ml-1 inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  statusFilter === 'conflicts'
                    ? 'bg-amber-500 text-white'
                    : 'bg-amber-50 text-amber-700 hover:bg-amber-100'
                }`}
                title="Entities with unresolved SAP-merge conflicts"
              >
                <AlertTriangle size={12} />
                {t('sk_conflicts_n').replace('{n}', String(conflictedCount))}
              </button>
            )}
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12 text-gray-500">
            <RefreshCw size={14} className="animate-spin mr-2" />
            {t('sk_loading_catalog')}
          </div>
        ) : isError ? (
          <div className="text-center py-12 border-2 border-dashed border-red-200 rounded-lg">
            <p className="text-sm text-red-600">{t('sk_load_failed')}</p>
            <button onClick={reload} className="mt-2 text-xs text-blue-600 hover:underline">
              {t('common_refresh')}
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 border-2 border-dashed border-gray-200 rounded-lg">
            <Library size={20} className="mx-auto mb-2 text-gray-300" />
            <p className="text-sm text-gray-500">
              {rows.length === 0
                ? t('sk_no_products_yet')
                : t('sk_no_products_filter')}
            </p>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            {/* Denser than the default table: `p-4` per cell is a width tax this
                table cannot afford now that cells carry two facts. */}
            <Table className="[&_td]:px-3 [&_td]:py-2 [&_th]:px-3">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-7 pr-0" />
                  <TableHead>{t('sk_col_name')}</TableHead>
                  <TableHead>{t('sk_col_layer')}</TableHead>
                  <TableHead>{t('sk_col_module')}</TableHead>
                  <TableHead>{t('sk_col_process')}</TableHead>
                  <TableHead>{t('sk_col_status')}</TableHead>
                  <TableHead className="text-right">{t('sk_col_version')}</TableHead>
                  <TableHead>{t('sk_col_domains')}</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((r) => (
                  <Fragment key={r.entityId}>
                    <TableRow>
                      <TableCell className="pr-0 align-top">
                        {r.yaml && (
                          <button
                            onClick={() => toggleExpanded(r.entityId)}
                            className="rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                            aria-expanded={expanded.has(r.entityId)}
                            aria-label={t('sk_row_details')}
                            title={t('sk_row_details')}
                          >
                            {expanded.has(r.entityId) ? (
                              <ChevronDown size={13} />
                            ) : (
                              <ChevronRight size={13} />
                            )}
                          </button>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="font-medium text-gray-900">{r.name}</div>
                        <code className="text-[11px] text-gray-400 font-mono">{r.entityId}</code>
                      </TableCell>
                      <TableCell>
                        <span className="text-xs capitalize text-gray-600">{r.layer ?? '—'}</span>
                      </TableCell>
                      <TableCell>
                        <span className="text-xs uppercase text-gray-600">{r.module ?? '—'}</span>
                      </TableCell>
                      {/* The business axis (standards §3.1). Truncated with the full
                          value on hover — it is the one header key that reads as a
                          phrase, so it gets a bounded column of its own. */}
                      <TableCell className="max-w-[12rem]">
                        <span
                          className="block truncate text-xs text-gray-600"
                          title={r.businessProcess ?? undefined}
                        >
                          {r.businessProcess ?? '—'}
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <StatusPill status={r.status} />
                          {r.pendingConflicts > 0 && (
                            <button
                              onClick={() => setConflictEntity({ id: r.entityId, name: r.name })}
                              className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 hover:bg-amber-100"
                              title={`${r.pendingConflicts} unresolved SAP-merge conflict(s) — click to resolve`}
                            >
                              <AlertTriangle size={10} />
                              {r.pendingConflicts}
                            </button>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-gray-700">
                        v{r.version}
                      </TableCell>
                      <TableCell>
                        <span className="text-xs text-gray-600">{r.domainCount}</span>
                        {r.domainCount > 1 && (
                          <span className="ml-2 rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-700">
                            reused
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <MenuDropdown
                          align="right"
                          title="Actions"
                          items={[
                            {
                              label: opening === r.entityId ? t('sk_action_opening') : t('common_edit'),
                              icon: <Pencil size={13} />,
                              disabled: opening !== null,
                              onClick: () => void handleEdit(r.entityId),
                            },
                            {
                              label: t('sk_action_history'),
                              icon: <HistoryIcon size={13} />,
                              onClick: () =>
                                navigate(`/history?yaml=${encodeURIComponent(r.entityId)}`),
                            },
                            {
                              label: t('common_delete'),
                              icon: <Trash2 size={13} />,
                              tone: 'danger',
                              onClick: () => setDeleteTarget(r),
                            },
                          ]}
                        />
                      </TableCell>
                    </TableRow>
                    {expanded.has(r.entityId) && r.yaml && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={99} className="pt-0">
                          <EntityHeaderDetail row={r.yaml} />
                        </TableCell>
                      </TableRow>
                    )}
                    </Fragment>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {conflictEntity && (
        <ConflictDialog
          entityId={conflictEntity.id}
          entityName={conflictEntity.name}
          // Resolving invalidates the shared lifecycle cache (mergeStore.resolve),
          // so the row badge/count + "Conflicts (N)" filter update live — even on
          // a partial resolution. Closing just drops the dialog.
          onClose={() => setConflictEntity(null)}
        />
      )}

      {/* Edit reuses the SAME global EditPanel the Graph page opens (store-driven
          modal). Opens when handleEdit() calls startEdit(); save/cancel clear the
          editor state and (on save) invalidate the lifecycle cache → list refreshes. */}
      {editingNodeId && <EditPanel onClose={() => cancelEdit()} />}

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(o) => {
          if (!o) setDeleteTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('sk_delete_title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('sk_delete_desc_preamble')} <b>{deleteTarget?.name}</b>{' '}
              <code className="font-mono text-xs">{deleteTarget?.entityId}</code> —{' '}
              {t('sk_delete_desc_body')} <b>{t('sk_delete_desc_unpublished')}</b>
              {deleteTarget && deleteTarget.domainCount > 0 ? (
                <>
                  {' '}
                  {t('sk_delete_desc_domains_prefix')} <b>{deleteTarget.domainCount}</b>{' '}
                  {deleteTarget.domainCount === 1
                    ? t('sk_delete_desc_domain')
                    : t('sk_delete_desc_domains')}
                </>
              ) : null}
              . {t('sk_delete_desc_suffix')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>{t('common_cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                void confirmDelete()
              }}
              className="bg-rose-600 hover:bg-rose-700 focus:ring-rose-600"
            >
              {deleting ? t('common_deleting') : t('common_delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
