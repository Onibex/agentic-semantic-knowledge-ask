/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

/**
 * Workspace home (design spec fig. 2, reconciled with UX_CHANGES audit).
 *
 * A single screen: a left RAIL of workspaces (with Business-Domain counts) +
 * the selected workspace's detail on the right — its Business Domain cards,
 * each showing its data products as chips (layer colour + status dot + reused),
 * with Open domain / Edit / Manage data products / Publish domain → dev·prod.
 *
 * NOTE (audit Q7): there is intentionally NO environment switcher — promotion is
 * per data product / per domain via the Publish buttons, not a global chip.
 *
 * "Open domain →" routes to the Graph scoped to the active workspace (the full
 * per-Business-Domain canvas is design-spec §03, a separate screen — TODO).
 */

import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  Edit3,
  LayoutGrid,
  Loader2,
  Pencil,
  Plus,
  Rocket,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import {
  deleteWorkspace,
  getWorkspace,
  listWorkspaceBusinessDomains,
  updateWorkspace,
} from '@/api/client'
import type {
  BusinessDomain,
  DataProductLifecycle,
  Workspace,
  YAMLNodeSummary,
} from '@/api/types'
import { invalidateLifecycle, useDataProductCatalog } from '@/hooks/queries/catalogQueries'
import { useYamlList } from '@/hooks/queries/yamlQueries'
import { DataProductChip } from '@/components/lifecycle/DataProductChip'
import { CreateBusinessDomainDialog } from '@/components/workspaces/CreateBusinessDomainDialog'
import { CreateWorkspaceDialog } from '@/components/workspaces/CreateWorkspaceDialog'
import { DomainPublishDialog } from '@/components/workspaces/DomainPublishDialog'
import { EditBusinessDomainDialog } from '@/components/workspaces/EditBusinessDomainDialog'
import { EditWorkspaceDialog } from '@/components/workspaces/EditWorkspaceDialog'
import { ManageEntitiesDialog } from '@/components/workspaces/ManageEntitiesDialog'
import { WorkspacesRail } from '@/components/workspaces/WorkspacesRail'
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
import { Button } from '@/components/ui/button'
import { useWorkspaceStore } from '@/store/workspaceStore'
import { useTranslation } from '@/hooks/useTranslation'

export default function WorkspaceHome() {
  const { t } = useTranslation()
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()

  // ── Rail (all workspaces + BD counts) ────────────────────────────────────
  const available = useWorkspaceStore((s) => s.available)
  const railLoading = useWorkspaceStore((s) => s.loading)
  const loadWorkspaces = useWorkspaceStore((s) => s.loadWorkspaces)
  const setActive = useWorkspaceStore((s) => s.setActive)
  const [bdCounts, setBdCounts] = useState<Record<string, number>>({})
  const [createWsOpen, setCreateWsOpen] = useState(false)

  // ── Selected workspace detail ────────────────────────────────────────────
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [domains, setDomains] = useState<BusinessDomain[]>([])
  // Shared caches (catalog scoped to the open workspace). invalidateLifecycle()
  // from any mutation re-renders the BD-card status chips.
  const { data: lifecycle = [] } = useDataProductCatalog(
    { workspaceId: workspace?.id },
    { enabled: Boolean(workspace?.id) },
  )
  const { data: yamls = [] } = useYamlList()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [editOpen, setEditOpen] = useState(false)
  const [createBdOpen, setCreateBdOpen] = useState(false)
  const [manageProductsFor, setManageProductsFor] = useState<BusinessDomain | null>(null)
  const [editBdFor, setEditBdFor] = useState<BusinessDomain | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  // The domain + env the publish dialog is open for (null = closed). The dialog
  // owns the checklist + live per-DP progress streaming.
  const [publishFor, setPublishFor] = useState<{ bd: BusinessDomain; env: 'dev' | 'prod' } | null>(
    null,
  )

  // Load the workspace list once (for the rail).
  useEffect(() => {
    void loadWorkspaces()
  }, [loadWorkspaces])

  // BD counts for the rail — one lightweight list per workspace, best-effort.
  useEffect(() => {
    let cancelled = false
    if (available.length === 0) return
    Promise.all(
      available.map((ws) =>
        listWorkspaceBusinessDomains(ws.id)
          .then((bds) => [ws.id, bds.length] as const)
          .catch(() => [ws.id, 0] as const),
      ),
    ).then((pairs) => {
      if (!cancelled) setBdCounts(Object.fromEntries(pairs))
    })
    return () => {
      cancelled = true
    }
  }, [available])

  const load = useCallback(async () => {
    if (!slug) {
      setWorkspace(null)
      setDomains([])
      setError(null)
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const [ws, bds] = await Promise.all([getWorkspace(slug), listWorkspaceBusinessDomains(slug)])
      setWorkspace(ws)
      setDomains(bds)
      setActive(ws.id) // keep the rest of the SPA scoped to the open workspace
      // Lifecycle (status chips) + entity metadata come from the shared query
      // caches (useDataProductCatalog / useYamlList) — no manual fetch here.
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workspace')
    } finally {
      setLoading(false)
    }
  }, [slug, setActive])

  useEffect(() => {
    void load()
  }, [load])

  // Rail counts: the per-workspace fetched counts, with the OPEN workspace's
  // count overridden by its live BD list (so create/delete reflects instantly).
  // Derived, not an effect — avoids a setState-in-effect cascade.
  const railCounts = useMemo(
    () => (workspace ? { ...bdCounts, [workspace.id]: domains.length } : bdCounts),
    [bdCounts, workspace, domains.length],
  )

  const lcById = useMemo(() => {
    const m = new Map<string, DataProductLifecycle>()
    for (const d of lifecycle) m.set(d.entity_id, d)
    return m
  }, [lifecycle])

  const yamlById = useMemo(() => {
    const m = new Map<string, YAMLNodeSummary>()
    for (const y of yamls) m.set(y.id, y)
    return m
  }, [yamls])

  const nameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const y of yamls) if (y.name) m.set(y.id, y.name)
    return m
  }, [yamls])

  function openDomain(bd: BusinessDomain) {
    if (workspace) setActive(workspace.id)
    // Domain canvas (design-spec §03) — the graph scoped to this domain.
    navigate(`/workspaces/${workspace?.slug ?? slug}/domains/${bd.slug}`)
  }

  async function handleDelete() {
    if (!workspace) return
    setDeleting(true)
    try {
      const result = await deleteWorkspace(workspace.id)
      toast.success(`Workspace deleted (${result.business_domains_deleted} business domains removed)`)
      void loadWorkspaces()
      navigate('/workspaces')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not delete workspace')
    } finally {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  return (
    <div className="flex h-full overflow-hidden">
      <WorkspacesRail
        workspaces={available}
        counts={railCounts}
        activeSlug={slug}
        loading={railLoading}
        onSelect={(ws) => navigate(`/workspaces/${ws.slug}`)}
        onNew={() => setCreateWsOpen(true)}
      />

      <main className="flex-1 overflow-y-auto">
        {!slug ? (
          <EmptyState onNew={() => setCreateWsOpen(true)} />
        ) : loading && !workspace ? (
          <div className="flex items-center justify-center py-16 text-gray-500">
            <Loader2 size={16} className="animate-spin mr-2" />
            {t('common_loading')}
          </div>
        ) : error || !workspace ? (
          <div className="max-w-3xl mx-auto p-6">
            <div className="px-3 py-2.5 rounded-md bg-red-50 border border-red-200 text-sm text-red-900">
              {error || t('ws_not_found')}
            </div>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto p-6">
            {/* Workspace header */}
            <div className="flex items-start justify-between gap-4 mb-6">
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-3">
                  <h1 className="text-2xl font-semibold text-gray-900 truncate">{workspace.name}</h1>
                  <code className="text-sm text-gray-400 font-mono">{workspace.slug}</code>
                </div>
                {workspace.objective && (
                  <p className="text-sm text-gray-600 mt-1">{workspace.objective}</p>
                )}
              </div>
              <div className="flex gap-2 shrink-0">
                <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                  <Pencil size={12} />
                  <span className="ml-1.5">{t('common_edit')}</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setConfirmDelete(true)}
                  className="text-red-600 hover:text-red-700"
                >
                  <Trash2 size={12} />
                  <span className="ml-1.5">{t('common_delete')}</span>
                </Button>
              </div>
            </div>

            {workspace.description && (
              <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6 text-sm text-gray-700 whitespace-pre-wrap">
                {workspace.description}
              </div>
            )}

            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-lg font-semibold text-gray-900">
                {t('ws_business_domains_header')}{' '}
                <span className="text-sm font-normal text-gray-400">({domains.length})</span>
              </h2>
              <Button size="sm" onClick={() => setCreateBdOpen(true)}>
                <Plus size={14} />
                <span className="ml-1.5">{t('ws_new_bd_btn')}</span>
              </Button>
            </div>

            {domains.length === 0 ? (
              <div className="text-center py-12 border-2 border-dashed border-gray-200 rounded-lg">
                <div className="inline-flex items-center justify-center h-12 w-12 rounded-full bg-blue-50 mb-3">
                  <Boxes size={20} className="text-blue-600" />
                </div>
                <h3 className="text-base font-semibold text-gray-900 mb-1">{t('ws_no_domains_title')}</h3>
                <p className="text-sm text-gray-500 mb-4">
                  {t('ws_no_domains_desc')}
                </p>
                <Button size="sm" onClick={() => setCreateBdOpen(true)}>
                  <Plus size={14} />
                  <span className="ml-1.5">{t('ws_create_bd_btn')}</span>
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                {domains.map((bd) => (
                  <div
                    key={bd.id}
                    className="bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-300 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2">
                          <h3 className="text-base font-semibold text-gray-900 truncate">{bd.name}</h3>
                          <code className="text-xs text-gray-400 font-mono">{bd.slug}</code>
                        </div>
                        {bd.description && (
                          <p className="text-sm text-gray-600 mt-1 line-clamp-2">{bd.description}</p>
                        )}
                        <div className="text-xs text-gray-500 inline-flex items-center gap-1 mt-2">
                          <Boxes size={12} />
                          {bd.data_product_ids.length}{' '}
                          {bd.data_product_ids.length === 1 ? t('ws_data_product') : t('ws_data_products')}
                        </div>
                        {/* Data product chips (audit §5.5 / fig. 2): layer
                            colour + status dot + "reused" badge. */}
                        <div className="flex flex-wrap items-center gap-1.5 mt-2">
                          {bd.data_product_ids.map((id) => {
                            const y = yamlById.get(id)
                            const lc = lcById.get(id)
                            return (
                              <DataProductChip
                                key={id}
                                name={y?.name ?? id}
                                layer={y?.layer ?? null}
                                status={lc?.status ?? null}
                                reused={(lc?.business_domain_ids?.length ?? 0) > 1}
                                devPublished={!!lc?.dev_published}
                                prodPublished={!!lc?.prod_published}
                              />
                            )
                          })}
                          <button
                            onClick={() => setManageProductsFor(bd)}
                            className="inline-flex items-center gap-1 rounded-md border border-dashed border-gray-300 px-2 py-1 text-xs text-gray-500 hover:bg-gray-50"
                          >
                            <Plus size={11} /> data product
                          </button>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <Button variant="outline" size="sm" onClick={() => setEditBdFor(bd)} title="Edit name / slug / description">
                          <Pencil size={12} />
                          <span className="ml-1.5">{t('common_edit')}</span>
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setManageProductsFor(bd)}>
                          <Edit3 size={12} />
                          <span className="ml-1.5">{t('ws_manage_btn')}</span>
                        </Button>
                      </div>
                    </div>

                    <div className="mt-3 pt-3 border-t border-gray-100 flex items-center gap-2 flex-wrap">
                      <button
                        onClick={() => openDomain(bd)}
                        className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-800"
                      >
                        {t('ws_open_domain')} <ArrowRight size={12} />
                      </button>
                      <span className="flex-1" />
                      {bd.data_product_ids.length > 0 && (
                        <>
                          <span className="text-[11px] text-gray-400">{t('ws_publish_arrow')}</span>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPublishFor({ bd, env: 'dev' })}
                            className="text-blue-700 border-blue-300 hover:bg-blue-50"
                          >
                            <Rocket size={12} />
                            <span className="ml-1.5">dev</span>
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setPublishFor({ bd, env: 'prod' })}
                            className="text-green-700 border-green-300 hover:bg-green-50"
                          >
                            <Rocket size={12} />
                            <span className="ml-1.5">prod</span>
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>

      {/* Dialogs + modals */}
      <CreateWorkspaceDialog
        open={createWsOpen}
        onClose={() => setCreateWsOpen(false)}
        onCreated={(ws) => {
          setCreateWsOpen(false)
          toast.success(`Workspace "${ws.name}" created`)
          void loadWorkspaces()
          navigate(`/workspaces/${ws.slug}`)
        }}
      />

      {workspace && (
        <EditWorkspaceDialog
          open={editOpen}
          workspace={workspace}
          onClose={() => setEditOpen(false)}
          onSaved={(ws) => {
            setEditOpen(false)
            setWorkspace(ws)
            void loadWorkspaces()
            if (ws.slug !== slug) navigate(`/workspaces/${ws.slug}`, { replace: true })
            toast.success('Workspace updated')
          }}
          onPatch={(payload) => updateWorkspace(workspace.id, payload)}
        />
      )}

      {workspace && (
        <CreateBusinessDomainDialog
          open={createBdOpen}
          workspace={workspace}
          onClose={() => setCreateBdOpen(false)}
          onCreated={(bd) => {
            setCreateBdOpen(false)
            setDomains((prev) => [...prev, bd].sort((a, b) => a.slug.localeCompare(b.slug)))
            toast.success(`Business domain "${bd.name}" created`)
          }}
        />
      )}

      {manageProductsFor && (
        <ManageEntitiesDialog
          open
          businessDomain={manageProductsFor}
          onClose={() => setManageProductsFor(null)}
          onSaved={(updated) => {
            setManageProductsFor(null)
            setDomains((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
            toast.success(
              `Updated ${updated.data_product_ids.length} ${
                updated.data_product_ids.length === 1 ? 'data product' : 'data products'
              }`,
            )
          }}
        />
      )}

      {editBdFor && (
        <EditBusinessDomainDialog
          open
          businessDomain={editBdFor}
          onClose={() => setEditBdFor(null)}
          onSaved={(updated) => {
            setEditBdFor(null)
            setDomains((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
          }}
        />
      )}

      {publishFor && (
        <DomainPublishDialog
          open
          env={publishFor.env}
          businessDomainId={publishFor.bd.id}
          businessDomainName={publishFor.bd.name}
          members={publishFor.bd.data_product_ids}
          lifecycleById={lcById}
          nameById={nameById}
          onClose={() => setPublishFor(null)}
          onComplete={(summary) => {
            const { bd, env } = publishFor
            const msg = `${bd.name} → ${env}: ${summary.published} published, ${summary.skipped} skipped${
              summary.failed ? `, ${summary.failed} failed` : ''
            }`
            if (summary.failed) toast.error(msg)
            else toast.success(msg)
            // Shared cache → refresh this page's chips AND every other lifecycle view.
            invalidateLifecycle()
          }}
        />
      )}

      {workspace && (
        <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle className="flex items-center gap-2">
                <AlertTriangle size={16} className="text-red-600" />
                {t('ws_delete_ws_title')}
              </AlertDialogTitle>
              <AlertDialogDescription>
                <strong>{workspace.name}</strong>{' '}
                {t('ws_delete_ws_and_its')}{' '}
                <strong>{domains.length}</strong>{' '}
                {t('ws_delete_ws_domains_removed')}{' '}
                {t('ws_delete_ws_yamls_note')}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={deleting}>{t('common_cancel')}</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => void handleDelete()}
                disabled={deleting}
                className="bg-red-600 hover:bg-red-700"
              >
                {deleting ? (
                  <>
                    <Loader2 size={12} className="animate-spin mr-1.5" />
                    {t('common_deleting')}
                  </>
                ) : (
                  t('ws_delete_ws_confirm_btn')
                )}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  )
}

function EmptyState({ onNew }: { onNew: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="text-center max-w-sm">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-600 mb-3">
          <LayoutGrid size={22} />
        </div>
        <h2 className="text-base font-semibold text-gray-900">{t('ws_pick_workspace')}</h2>
        <p className="text-sm text-gray-500 mt-1 mb-4">
          {t('ws_choose_workspace_desc')}
        </p>
        <Button size="sm" onClick={onNew}>
          <Plus size={14} />
          <span className="ml-1.5">{t('ws_new_workspace_btn')}</span>
        </Button>
      </div>
    </div>
  )
}
