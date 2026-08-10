/**
 * Domain Canvas (design-spec §03 / fig. 3) — the React Flow graph scoped to a
 * single Business Domain. "The canvas IS the graph" (§10 #03): there is no
 * separate global Graph tab; opening a domain lands here.
 *
 * Reuse-first: this is a thin wrapper that scopes the shared graphStore to one
 * domain (`fetchAll({ businessDomain })`, server resolves its DPs + 1-hop) and
 * composes the SAME building blocks GraphPage uses — FilterPanel · YAMLGraph ·
 * DetailPanel / EditPanel. New here: the Workspace › Domain breadcrumb and the
 * domain-level Publish header (audit §6.5). No global env switcher (audit Q7).
 */

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronRight, Loader2, Rocket } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from '../hooks/useTranslation'

import { YAMLGraph } from '../components/graph/YAMLGraph'
import { FilterPanelBody } from '../components/panels/FilterPanel'
import { DetailPanel } from '../components/panels/DetailPanel'
import { EditPanel } from '../components/editor/EditPanel'
import { DomainKnowledgePanel } from '../components/workspaces/DomainKnowledgePanel'
import { DomainPublishDialog } from '../components/workspaces/DomainPublishDialog'
import { useGraphStore } from '../store/graphStore'
import { useEditorStore } from '../store/editorStore'
import { useWorkspaceStore } from '../store/workspaceStore'
import { usePublishedStore } from '../store/publishedStore'
import {
  addDataProductToDomain,
  getWorkspace,
  getYaml,
  listWorkspaceBusinessDomains,
  removeDataProductFromDomain,
} from '../api/client'
import type { BusinessDomain, Workspace, YAMLNode } from '../api/types'
import {
  invalidateLifecycle,
  invalidateLifecycleDebounced,
  useDataProductCatalog,
} from '../hooks/queries/catalogQueries'

export default function DomainCanvasPage() {
  const { t } = useTranslation()
  const { slug, bdSlug } = useParams<{ slug: string; bdSlug: string }>()

  const {
    fetchAll, reset, loading, error, rawNodes, selectedNode, mergeNodes, removeNodes, revealNode,
    setSearch, clearSearch, searchQuery, searchResults, focusNodeId, setFocus,
  } = useGraphStore()
  const focusNode = focusNodeId ? rawNodes.find((n) => n.id === focusNodeId) ?? null : null
  const { editingNodeId } = useEditorStore()
  const setActive = useWorkspaceStore((s) => s.setActive)
  const refreshPublished = usePublishedStore((s) => s.refresh)

  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [bd, setBd] = useState<BusinessDomain | null>(null)
  const [resolving, setResolving] = useState(true)
  const [resolveError, setResolveError] = useState<string | null>(null)
  // Shared lifecycle cache — any mutation calling invalidateLifecycle() (incl.
  // a per-DP publish done in the DetailPanel) re-renders the summary chip.
  const { data: lifecycle = [] } = useDataProductCatalog()
  const [mode, setMode] = useState<'view' | 'edit'>('view')
  const [localSearch, setLocalSearch] = useState('')
  const [railTab, setRailTab] = useState<'filters' | 'knowledge'>('filters')
  // Which env the publish dialog is open for (null = closed). The dialog owns
  // the checklist + live per-DP progress streaming.
  const [publishEnv, setPublishEnv] = useState<'dev' | 'prod' | null>(null)

  // ── Resolve workspace + BD from the route slugs ──────────────────────────
  useEffect(() => {
    let cancelled = false
    async function resolve() {
      if (!slug || !bdSlug) return
      setResolving(true)
      setResolveError(null)
      try {
        const [ws, bds] = await Promise.all([
          getWorkspace(slug),
          listWorkspaceBusinessDomains(slug),
        ])
        if (cancelled) return
        const found = bds.find((b) => b.slug === bdSlug) ?? null
        setWorkspace(ws)
        setBd(found)
        if (ws) setActive(ws.id)
        if (!found) setResolveError(`Domain "${bdSlug}" not found in workspace "${slug}".`)
      } catch (e) {
        if (!cancelled) setResolveError(e instanceof Error ? e.message : 'Failed to load domain')
      } finally {
        if (!cancelled) setResolving(false)
      }
    }
    void resolve()
    return () => {
      cancelled = true
    }
  }, [slug, bdSlug, setActive])

  // ── Scope the graph to this domain. Keyed on the BD *id* (a primitive), NOT
  // the bd object: add/remove change data_product_ids but not the id, so they
  // must NOT retrigger this full refetch (which reset the user's filters and
  // clobbered the incremental replaceNode/removeNode update). Only navigating
  // to a different domain (id changes) refetches. ──────────────────────────
  const bdId = bd?.id ?? null
  useEffect(() => {
    if (!bdId) {
      reset()
      return
    }
    reset()
    void fetchAll({ businessDomain: bdId })
  }, [bdId, fetchAll, reset])

  useEffect(() => {
    void refreshPublished()
  }, [refreshPublished])

  useEffect(() => {
    if (!selectedNode) setMode('view')
  }, [selectedNode])

  useEffect(() => {
    const t = setTimeout(() => {
      if (localSearch.trim()) setSearch(localSearch.trim())
      else clearSearch()
    }, 300)
    return () => clearTimeout(t)
  }, [localSearch, setSearch, clearSearch])

  // Remove the selected entity FROM THIS DOMAIN — membership only (audit D3).
  // Drops the id from the BD's data_product_ids; never deletes the YAML nor
  // unpublishes the runtime index.
  async function removeFromDomain() {
    if (!bd || !selectedNode) return
    const entityId = selectedNode.id
    const toastId = toast.loading(t('dc_toast_removing').replace('{id}', entityId))
    try {
      // Atomic single-entity remove (server scripted update) instead of PATCHing
      // the whole filtered array from this render's (possibly stale) bd.
      const updated = await removeDataProductFromDomain(bd.id, entityId)
      setBd(updated)
      // Incremental: drop the entity + any composed_of bronze that NO other
      // loaded entity still references (a shared bronze stays — mirrors the
      // server's publish cascade). Preserves filters; no full N+1 refetch.
      const nodes = useGraphStore.getState().rawNodes
      const removed = nodes.find((n) => n.id === entityId)
      const stillReferenced = new Set<string>()
      for (const n of nodes) {
        if (n.id === entityId) continue
        for (const ref of n.composed_of ?? []) stillReferenced.add(ref)
      }
      const orphanBronzes = (removed?.composed_of ?? []).filter(
        (ref) =>
          !stillReferenced.has(ref) &&
          nodes.some((n) => n.id === ref && n.layer === 'bronze'),
      )
      removeNodes([entityId, ...orphanBronzes])
      invalidateLifecycle()
      toast.success(
        t('dc_toast_removed').replace('{id}', entityId).replace('{domain}', bd.name),
        { id: toastId },
      )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not remove from domain', { id: toastId })
    }
  }

  // Add a Data Product to this domain (Knowledge rail → drag onto canvas or "+").
  // Membership-only: appends to the BD's data_product_ids, then splices the new
  // node in (incremental — preserves filters, no full refetch). Also pulls in the
  // entity's composed_of bronzes that exist, so a dropped Silver arrives WITH its
  // source tables (matching a fresh domain load) instead of as an orphan node.
  // Bronzes are graph context only — membership stays Silver-only and the server
  // re-derives them as one-hop neighbors next load. Refs that don't resolve are
  // skipped (pure no-op — same contract as remove).
  async function addToDomain(entityId: string) {
    if (!bd || (bd.data_product_ids ?? []).includes(entityId)) return
    const bdId = bd.id
    const bdName = bd.name
    // Optimistic membership FIRST so the Knowledge list drops the item the
    // instant you click. The functional updater reads the LATEST bd, so a rapid
    // burst accumulates correctly — the old code only updated after the whole
    // round-trip chain resolved, which is why fast clicks 2..N "didn't
    // disappear". The server add is atomic + idempotent, so we reconcile with
    // its authoritative response (by union, never dropping ids a later click
    // already added) and roll back only on failure.
    setBd((prev) =>
      prev && prev.id === bdId && !(prev.data_product_ids ?? []).includes(entityId)
        ? { ...prev, data_product_ids: [...(prev.data_product_ids ?? []), entityId] }
        : prev,
    )
    const toastId = toast.loading(t('dc_toast_adding').replace('{id}', entityId))
    try {
      const updated = await addDataProductToDomain(bdId, entityId)
      setBd((prev) => {
        if (!prev || prev.id !== bdId) return prev
        // Union server truth with the optimistic set — monotonic under a burst,
        // so an older in-flight response can't drop a just-added id (no flicker).
        const merged = Array.from(
          new Set([...(prev.data_product_ids ?? []), ...(updated.data_product_ids ?? [])]),
        )
        return { ...updated, data_product_ids: merged }
      })
      const node = await getYaml(entityId)
      const present = new Set(useGraphStore.getState().rawNodes.map((n) => n.id))
      const bronzeRefs = (node.composed_of ?? []).filter((ref) => !present.has(ref))
      const bronzes = (
        await Promise.all(bronzeRefs.map((ref) => getYaml(ref).catch(() => null)))
      ).filter((n): n is YAMLNode => !!n && n.layer === 'bronze')
      mergeNodes([node, ...bronzes])
      revealNode(entityId) // show the entity even if the current role/layer filter would hide it
      invalidateLifecycleDebounced() // coalesce the catalog refetch across a burst of adds
      toast.success(
        t('dc_toast_added').replace('{id}', entityId).replace('{domain}', bdName),
        { id: toastId },
      )
    } catch (e) {
      // Roll back the optimistic membership on failure.
      setBd((prev) =>
        prev && prev.id === bdId
          ? {
              ...prev,
              data_product_ids: (prev.data_product_ids ?? []).filter((id) => id !== entityId),
            }
          : prev,
      )
      toast.error(e instanceof Error ? e.message : 'Could not add to domain', { id: toastId })
    }
  }

  // ── Resolve states ───────────────────────────────────────────────────────
  if (resolving) {
    return (
      <div className="flex h-full items-center justify-center bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }
  if (resolveError || !bd) {
    return (
      <div className="flex h-full items-center justify-center bg-gray-50">
        <div className="max-w-md text-center px-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-1">{t('dc_not_found_title')}</h2>
          <p className="text-sm text-gray-600 mb-4">{resolveError ?? t('dc_unknown_domain')}</p>
          <Link
            to="/workspaces"
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            {t('dc_back_to_workspaces')}
          </Link>
        </div>
      </div>
    )
  }

  // Summary chip (audit §6.5): N data products · ✓ M ready for prod · ⚠ K need dev first.
  //  - need dev first: working has unpublished changes (In Review) → must publish to dev first.
  //  - ready for prod: on dev (Released) and prod is behind dev → can be promoted.
  const inDomain = lifecycle.filter((lc) => (bd.data_product_ids ?? []).includes(lc.entity_id))
  const total = (bd.data_product_ids ?? []).length
  const needsDevList = inDomain.filter((lc) => lc.status === 'In Review')
  const needsDev = needsDevList.length
  const readyForProdList = inDomain.filter(
    (lc) =>
      lc.status === 'Released' &&
      lc.dev_published != null &&
      (lc.prod_published == null || lc.prod_published.sha !== lc.dev_published.sha),
  )
  const readyForProd = readyForProdList.length
  // Queryable scope per env (Option B): the agent can only answer over members
  // actually published to the target env. A member in the domain but not yet
  // published to {env} is NOT answerable there — this makes that gap legible.
  const queryableDev = inDomain.filter((lc) => lc.dev_published != null).length
  const queryableProd = inDomain.filter((lc) => lc.prod_published != null).length
  const notInProd = inDomain
    .filter((lc) => lc.prod_published == null)
    .map((lc) => lc.entity_id)
  // Maps the publish dialog needs: lifecycle gate + display names per member.
  // Plain (not memoised) — after the early returns above, so no hook here.
  const lifecycleById = new Map(inDomain.map((lc) => [lc.entity_id, lc]))
  const nameById = new Map(rawNodes.map((n) => [n.id, n.name]))

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header: breadcrumb + domain publish (no env switcher — audit Q7) */}
      <div className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-2">
        <nav className="flex items-center gap-1.5 text-sm min-w-0">
          <Link to={`/workspaces/${slug}`} className="text-gray-500 hover:text-gray-800 truncate">
            {workspace?.name || slug}
          </Link>
          <ChevronRight className="h-3.5 w-3.5 text-gray-300 shrink-0" />
          <span className="font-semibold text-gray-900 truncate">{bd.name}</span>
        </nav>

        <span
          className="ml-2 text-xs text-gray-500"
          title={needsDev ? `Need dev first: ${needsDevList.map((l) => l.entity_id).join(', ')}` : undefined}
        >
          {total} {total === 1 ? t('dc_data_product') : t('dc_data_products')} · ✓ {readyForProd} {t('dc_ready_for_prod')} · ⚠ {needsDev} {t('dc_need_dev_first')}
        </span>
        <span
          className="text-xs text-gray-500"
          title={
            notInProd.length
              ? t('dc_tooltip_not_in_prod').replace('{list}', notInProd.join(', '))
              : t('dc_tooltip_all_in_prod')
          }
        >
          {t('dc_queryable_summary')
            .replace('{dev}', String(queryableDev))
            .replace('{prod}', String(queryableProd))
            .replace('{total}', String(total))}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setPublishEnv('dev')}
            disabled={publishEnv !== null}
            className="inline-flex items-center gap-1.5 text-xs font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-60 px-3 py-1.5 shadow-sm"
            title="Choose which Data Products with pending changes to publish to dev, and watch each one publish."
          >
            <Rocket className="h-3.5 w-3.5" />
            {t('dc_publish_dev')}
          </button>
          <button
            onClick={() => setPublishEnv('prod')}
            disabled={publishEnv !== null}
            className="inline-flex items-center gap-1.5 text-xs font-medium rounded-md border border-emerald-300 bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-60 px-3 py-1.5 shadow-sm"
            title="Choose which ready Data Products to promote to prod (per-DP gate applies), and watch each one publish."
          >
            <Rocket className="h-3.5 w-3.5" />
            {t('dc_publish_prod')}
          </button>
        </div>
      </div>

      {/* Body: rail (Filters | Knowledge) · graph · inspector */}
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-56 shrink-0 bg-white border-r border-gray-200 flex flex-col overflow-hidden">
          <div className="flex border-b border-gray-200 text-xs font-medium shrink-0">
            <button
              onClick={() => setRailTab('filters')}
              className={`flex-1 px-3 py-2 ${
                railTab === 'filters'
                  ? 'text-blue-700 border-b-2 border-blue-600'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t('dc_tab_filters')}
            </button>
            <button
              onClick={() => setRailTab('knowledge')}
              className={`flex-1 px-3 py-2 ${
                railTab === 'knowledge'
                  ? 'text-blue-700 border-b-2 border-blue-600'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t('dc_tab_knowledge')}
            </button>
          </div>
          {railTab === 'filters' ? (
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">
              <FilterPanelBody />
            </div>
          ) : (
            <DomainKnowledgePanel domain={bd} onAdd={(id) => void addToDomain(id)} />
          )}
        </aside>

        <div className="flex-1 relative overflow-hidden">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
              <div className="flex flex-col items-center gap-2">
                <div className="w-8 h-8 border-4 border-blue-400 border-t-transparent rounded-full animate-spin" />
                <span className="text-sm text-gray-500">{t('dc_loading')}</span>
              </div>
            </div>
          )}
          {error && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-2 rounded shadow">
              {error}
            </div>
          )}
          {!loading && !error && rawNodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-50">
              <div className="max-w-sm text-center px-6 text-sm text-gray-600">
                {t('dc_no_data_products')}
              </div>
            </div>
          )}

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

          <div className="absolute top-3 left-3 z-10 flex items-center gap-2">
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
          </div>

          <YAMLGraph onDropEntity={(id) => void addToDomain(id)} />
        </div>

        {/* Right panel: edit mode takes priority over detail view */}
        {mode === 'edit' && editingNodeId ? (
          <EditPanel onClose={() => setMode('view')} />
        ) : (
          selectedNode && (
            <DetailPanel
              onEdit={() => setMode('edit')}
              domainName={bd.name}
              onRemoveFromDomain={() => void removeFromDomain()}
            />
          )
        )}
      </div>

      {/* Domain publish — checklist + live per-DP progress (streaming) */}
      {publishEnv && (
        <DomainPublishDialog
          open={publishEnv !== null}
          env={publishEnv}
          businessDomainId={bd.id}
          businessDomainName={bd.name}
          members={bd.data_product_ids ?? []}
          lifecycleById={lifecycleById}
          nameById={nameById}
          onClose={() => setPublishEnv(null)}
          onComplete={(summary) => {
            if (summary.failed > 0) {
              toast.error(
                t('dc_toast_publish_failed')
                  .replace('{env}', publishEnv ?? '')
                  .replace('{n}', String(summary.failed))
              )
            }
            invalidateLifecycle()
            void refreshPublished()
          }}
        />
      )}
    </div>
  )
}
