/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  BrainCircuit,
  RefreshCw,
  Plus,
  X,
  Loader2,
  Zap,
  Pencil,
  Trash2,
  MoreVertical,
  Check,
  AlertTriangle,
  Star,
  Boxes,
  Share2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { llmConnApi, embedderApi } from '@/api/client'
import { ProviderLogo } from '@/components/ProviderLogo'
import { useTranslation } from '@/hooks/useTranslation'
import type { ProviderSpec, LlmConnectionView, SecretsGetResponse } from '@/api/types'

const PROVIDER_META: Record<string, { color: string }> = {
  openai: { color: '#10a37f' },
  anthropic: { color: '#d97757' },
  bedrock: { color: '#f0972a' },
  gemini: { color: '#4285f4' },
  vertex_ai: { color: '#34a853' },
  azure: { color: '#0078d4' },
  databricks: { color: '#ee4b2e' },
  huggingface: { color: '#e6a817' },
  sap_aicore: { color: '#0aa8e0' },
}
function meta(provider: string) {
  return PROVIDER_META[provider] ?? { color: '#64748b' }
}

const MODEL_SUGGESTIONS: Record<string, string[]> = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'o3', 'o4-mini'],
  anthropic: ['claude-sonnet-5', 'claude-opus-4-8', 'claude-haiku-4-5-20251001'],
  bedrock: ['amazon.nova-pro-v1:0', 'anthropic.claude-sonnet-5', 'amazon.titan-embed-text-v2:0'],
  gemini: ['gemini-2.0-flash', 'gemini-1.5-pro'],
  vertex_ai: ['gemini-2.0-flash', 'text-embedding-004'],
  azure: ['gpt-4o'],
  databricks: ['databricks-dbrx-instruct'],
  huggingface: ['sentence-transformers/all-MiniLM-L6-v2'],
  sap_aicore: ['gpt-4o', 'text-embedding-3-large'],
}

const FIELD_LABELS: Record<string, string> = {
  api_key: 'API Key',
  api_base: 'API Base',
  api_version: 'API Version',
  deployment_id: 'Deployment ID',
  AWS_ACCESS_KEY_ID: 'AWS Access Key ID',
  AWS_SECRET_ACCESS_KEY: 'AWS Secret Access Key',
  AWS_SESSION_TOKEN: 'AWS Session Token',
  AWS_BEARER_TOKEN_BEDROCK: 'AWS Bedrock Bearer Token',
  AWS_REGION: 'AWS Region',
  AWS_REGION_NAME: 'AWS Region Name',
  GOOGLE_APPLICATION_CREDENTIALS: 'Service Account (JSON path)',
  VERTEXAI_PROJECT: 'Project ID',
  VERTEXAI_LOCATION: 'Location',
}
const FIELD_HINTS: Record<string, string> = {
  deployment_id: 'From your SAP AI Core service key — uploaded once in Setup › AI Core.',
  api_base: 'Optional. Leave blank for the provider default.',
  api_version: 'Optional.',
  AWS_SESSION_TOKEN: 'Optional — only for temporary credentials.',
  AWS_REGION: 'e.g. us-east-1',
}
function labelFor(name: string): string {
  return (
    FIELD_LABELS[name] ??
    name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  )
}

function summarize(provider: string, model: string): string {
  return model ? `${provider} · ${model}` : provider
}

function alpha(hex: string): string {
  return hex + '26'
}

interface FormState {
  name: string
  provider: string
  model: string
  values: Record<string, string>
}

function emptyForm(name: string, spec: ProviderSpec | undefined): FormState {
  const values: Record<string, string> = {}
  if (spec) for (const f of spec.fields) values[f.name] = ''
  return { name, provider: spec?.id ?? '', model: '', values }
}

function formFromConnection(conn: LlmConnectionView): FormState {
  const values: Record<string, string> = {}
  for (const row of conn.fields) values[row.name] = row.sensitive ? '' : row.value
  return { name: conn.name, provider: conn.provider, model: conn.model, values }
}

function formFromEmbedder(emb: SecretsGetResponse): FormState {
  const values: Record<string, string> = {}
  for (const row of emb.fields) values[row.name] = row.sensitive ? '' : row.value
  return { name: '', provider: emb.provider, model: emb.model, values }
}

export function LlmProvidersPage() {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [providers, setProviders] = useState<ProviderSpec[]>([])
  const [connections, setConnections] = useState<LlmConnectionView[]>([])
  const [active, setActive] = useState<string | null>(null)
  const [embedder, setEmbedder] = useState<SecretsGetResponse | null>(null)

  const [drawer, setDrawer] = useState<{ kind: 'conn' | 'emb'; editingId?: string } | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [saving, setSaving] = useState(false)

  const [testing, setTesting] = useState<Set<string>>(new Set())
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<LlmConnectionView | null>(null)

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    const close = () => setMenuOpen(null)
    if (menuOpen) {
      window.addEventListener('click', close)
      return () => window.removeEventListener('click', close)
    }
  }, [menuOpen])

  async function load() {
    setLoading(true)
    try {
      const [prov, list, emb] = await Promise.all([
        llmConnApi.providers(),
        llmConnApi.list(),
        embedderApi.get(),
      ])
      setProviders(prov.providers)
      setConnections(list.connections)
      setActive(list.active.active)
      setEmbedder(emb)
    } catch (err) {
      toast.error(`Failed to load: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  const providerById = useMemo(() => {
    const m: Record<string, ProviderSpec> = {}
    for (const p of providers) m[p.id] = p
    return m
  }, [providers])

  const activeConn = connections.find((c) => c.id === active)

  function openAdd() {
    setDrawer({ kind: 'conn' })
    setForm(null)
  }
  function openEdit(conn: LlmConnectionView) {
    setDrawer({ kind: 'conn', editingId: conn.id })
    setForm(formFromConnection(conn))
  }
  function openEmbedder() {
    setDrawer({ kind: 'emb' })
    setForm(embedder ? formFromEmbedder(embedder) : { name: '', provider: '', model: '', values: {} })
  }
  function closeDrawer() {
    setDrawer(null)
    setForm(null)
  }

  function pickProvider(id: string) {
    const spec = providerById[id]
    setForm((f) => emptyForm(f?.name ?? '', spec))
  }
  function setValue(name: string, value: string) {
    setForm((f) => (f ? { ...f, values: { ...f.values, [name]: value } } : f))
  }

  const canSave = !!form && !!form.provider && (drawer?.kind === 'emb' || !!form.name.trim())

  async function save() {
    if (!form || !drawer) return
    setSaving(true)
    try {
      if (drawer.kind === 'emb') {
        await embedderApi.save({ provider: form.provider, model: form.model.trim(), fields: form.values })
        toast.success(t('llm_toast_emb_saved'))
      } else if (drawer.editingId) {
        await llmConnApi.update(drawer.editingId, {
          name: form.name.trim(),
          provider: form.provider,
          model: form.model.trim(),
          fields: form.values,
        })
        toast.success(t('llm_toast_saved').replace('{name}', form.name.trim()))
      } else {
        const created = await llmConnApi.create({
          name: form.name.trim(),
          provider: form.provider,
          model: form.model.trim(),
          fields: form.values,
        })
        if (connections.length === 0) await llmConnApi.setActive(created.id)
        toast.success(t('llm_toast_added').replace('{name}', form.name.trim()))
      }
      closeDrawer()
      await load()
    } catch (err) {
      toast.error(`Save failed: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  async function runTest(conn: LlmConnectionView) {
    setTesting((s) => new Set(s).add(conn.id))
    try {
      const res = await llmConnApi.test(conn.id)
      if (res.success) toast.success(`${conn.name}: ${res.detail} (${res.latency_ms} ms)`)
      else toast.error(`${conn.name}: ${res.error ?? res.detail}`)
    } finally {
      setTesting((s) => {
        const n = new Set(s)
        n.delete(conn.id)
        return n
      })
    }
  }

  const [testingEmb, setTestingEmb] = useState(false)
  async function testEmbedder() {
    setTestingEmb(true)
    try {
      const res = await embedderApi.test()
      if (res.success) toast.success(`Embedder: ${res.detail} (${res.latency_ms} ms)`)
      else toast.error(`Embedder: ${res.error ?? res.detail}`)
    } finally {
      setTestingEmb(false)
    }
  }

  async function setActiveConn(id: string | null) {
    const prev = active
    setActive(id)
    try {
      const res = await llmConnApi.setActive(id)
      setActive(res.active)
      if (id) {
        const conn = connections.find((c) => c.id === id)
        toast.success(t('llm_toast_activated').replace('{name}', conn?.name ?? 'Connection'))
      } else {
        toast.message(t('llm_toast_no_active'))
      }
    } catch (err) {
      setActive(prev)
      toast.error(`Could not update active: ${(err as Error).message}`)
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    const conn = pendingDelete
    setPendingDelete(null)
    try {
      await llmConnApi.remove(conn.id)
      toast.success(t('llm_toast_deleted').replace('{name}', conn.name))
      await load()
    } catch (err) {
      toast.error(`Delete failed: ${(err as Error).message}`)
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-lg bg-violet-50 border border-violet-200 flex items-center justify-center">
              <BrainCircuit size={16} className="text-violet-600" />
            </div>
            <h1 className="text-lg font-semibold text-slate-900">{t('llm_title')}</h1>
          </div>
          <p className="text-sm text-slate-500 ml-10 max-w-xl">
            {t('llm_desc')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 transition-colors py-1.5 px-2 rounded hover:bg-slate-100"
          >
            <RefreshCw size={13} className={cn(loading && 'animate-spin')} />
            {t('common_refresh')}
          </button>
          <button
            onClick={openAdd}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors shadow-sm"
          >
            <Plus size={15} />
            {t('llm_btn_add')}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-500 py-10">
          <Loader2 size={16} className="animate-spin" />
          {t('llm_loading')}
        </div>
      ) : (
        <>
          {/* Active model */}
          <div className="relative bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3.5 overflow-hidden mb-7">
            <div className="absolute left-0 top-0 bottom-0 w-1 bg-violet-600" />
            <div className="flex items-center justify-between mb-2.5 pl-1.5">
              <span className="text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5 text-violet-700">
                <Star size={12} />
                {t('llm_active_model_label')}
                <span className="text-slate-400 font-semibold normal-case tracking-normal">
                  {t('llm_active_used_by_chat')}
                </span>
              </span>
              <select
                value={active ?? ''}
                onChange={(e) => setActiveConn(e.target.value || null)}
                className="text-xs border border-slate-300 rounded-md px-2 py-1 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 max-w-[45%]"
              >
                <option value="">{t('common_none_option')}</option>
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            {activeConn ? (
              <div className="flex items-center gap-3 pl-1.5">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
                  style={{ backgroundColor: alpha(meta(activeConn.provider).color), color: meta(activeConn.provider).color }}
                >
                  <ProviderLogo id={activeConn.provider} size={20} />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-800 truncate">{activeConn.name}</div>
                  <div className="text-xs text-slate-500 font-mono truncate">
                    {summarize(activeConn.provider, activeConn.model)}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 pl-1.5 text-xs text-amber-600 font-medium">
                <AlertTriangle size={14} />
                {t('llm_no_active')}
              </div>
            )}
          </div>

          {/* Connection list */}
          <div className="flex items-center justify-between mb-3 px-0.5">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">{t('llm_section_all')}</h2>
            <span className="text-xs text-slate-400 font-semibold">
              {t('llm_conn_count').replace('{n}', String(connections.length))}
            </span>
          </div>

          {connections.length === 0 ? (
            <div className="text-center py-14 border-2 border-dashed border-slate-200 rounded-xl bg-white">
              <div className="w-12 h-12 rounded-xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-3">
                <BrainCircuit size={22} />
              </div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">{t('llm_empty_title')}</h3>
              <p className="text-xs text-slate-500 mb-4">{t('llm_empty_desc')}</p>
              <button
                onClick={openAdd}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
              >
                <Plus size={15} /> {t('llm_btn_add')}
              </button>
            </div>
          ) : (
            <div className="space-y-2.5">
              {connections.map((conn) => (
                <div
                  key={conn.id}
                  className="bg-white rounded-xl border border-slate-200 shadow-sm hover:border-slate-300 hover:shadow-md transition-all px-4 py-3.5 flex items-center gap-4"
                >
                  <div
                    className="w-11 h-11 rounded-lg flex items-center justify-center text-sm font-bold shrink-0"
                    style={{ backgroundColor: alpha(meta(conn.provider).color), color: meta(conn.provider).color }}
                  >
                    <ProviderLogo id={conn.provider} size={24} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-slate-900">{conn.name}</span>
                      <span className="text-[11px] font-mono text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">
                        {conn.provider}
                      </span>
                      {active === conn.id && (
                        <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200">
                          {t('common_active')}
                        </span>
                      )}
                      {!conn.configured && (
                        <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-amber-50 text-amber-700 border border-amber-200">
                          {t('llm_badge_incomplete')}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500 font-mono mt-1 truncate">{conn.model || '—'}</div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0 relative">
                    <button
                      onClick={() => runTest(conn)}
                      disabled={testing.has(conn.id)}
                      className="flex items-center gap-1.5 text-xs font-medium border border-slate-300 rounded-md px-2.5 py-1.5 text-slate-700 hover:bg-slate-50 disabled:opacity-60 transition-colors"
                    >
                      {testing.has(conn.id) ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
                      {t('common_test')}
                    </button>
                    <button
                      onClick={() => openEdit(conn)}
                      className="flex items-center gap-1.5 text-xs font-medium border border-slate-300 rounded-md px-2.5 py-1.5 text-slate-700 hover:bg-slate-50 transition-colors"
                    >
                      <Pencil size={13} /> {t('common_edit')}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setMenuOpen(menuOpen === conn.id ? null : conn.id)
                      }}
                      className="w-8 h-8 flex items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 transition-colors"
                      aria-label="More"
                    >
                      <MoreVertical size={16} />
                    </button>
                    {menuOpen === conn.id && (
                      <div
                        className="absolute right-0 top-full mt-1 w-52 bg-white border border-slate-200 rounded-lg shadow-lg p-1.5 z-20"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 px-2.5 pt-1.5 pb-1">
                          {t('llm_activate_section')}
                        </div>
                        <button
                          onClick={() => {
                            setActiveConn(conn.id)
                            setMenuOpen(null)
                          }}
                          className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm text-slate-700 hover:bg-slate-100 transition-colors"
                        >
                          <Star size={14} />
                          {t('llm_set_active_model')}
                          {active === conn.id && <Check size={14} className="ml-auto text-violet-600" />}
                        </button>
                        <div className="h-px bg-slate-100 my-1.5" />
                        <button
                          onClick={() => {
                            setPendingDelete(conn)
                            setMenuOpen(null)
                          }}
                          className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm text-red-600 hover:bg-red-50 transition-colors"
                        >
                          <Trash2 size={14} /> {t('common_delete')}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Embedder (single, shared) */}
          <div className="flex items-center justify-between mb-3 px-0.5 mt-7">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">{t('llm_section_embedder')}</h2>
            <span className="text-xs text-slate-400 font-semibold">{t('llm_single_global')}</span>
          </div>
          <div className="relative bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3.5 overflow-hidden">
            <div className="absolute left-0 top-0 bottom-0 w-1 bg-cyan-600" />
            <div className="flex items-center justify-between mb-2.5 pl-1.5">
              <span className="text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5 text-cyan-700">
                <Boxes size={13} />
                {t('llm_embedding_model')}
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={testEmbedder}
                  disabled={testingEmb}
                  className="flex items-center gap-1.5 text-xs font-medium border border-slate-300 rounded-md px-2.5 py-1.5 text-slate-700 hover:bg-slate-50 disabled:opacity-60 transition-colors"
                >
                  {testingEmb ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
                  {t('common_test')}
                </button>
                <button
                  onClick={openEmbedder}
                  className="flex items-center gap-1.5 text-xs font-medium border border-slate-300 rounded-md px-2.5 py-1.5 text-slate-700 hover:bg-slate-50 transition-colors"
                >
                  <Pencil size={13} /> {t('common_edit')}
                </button>
              </div>
            </div>
            {embedder && embedder.provider ? (
              <div className="flex items-center gap-3 pl-1.5">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
                  style={{ backgroundColor: alpha(meta(embedder.provider).color), color: meta(embedder.provider).color }}
                >
                  <ProviderLogo id={embedder.provider} size={20} />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-800 truncate">{embedder.provider}</div>
                  <div className="text-xs text-slate-500 font-mono truncate">{embedder.model || '—'}</div>
                </div>
                <span className="ml-auto text-[11px] font-semibold rounded-full px-2 py-0.5 bg-cyan-50 text-cyan-700 border border-cyan-200 flex items-center gap-1">
                  <Share2 size={11} /> {t('llm_shared_label')}
                </span>
              </div>
            ) : (
              <div className="flex items-center gap-2 pl-1.5 text-xs text-amber-600 font-medium">
                <AlertTriangle size={14} />
                {t('llm_no_embedder')}
              </div>
            )}
            <p className="text-xs text-slate-400 mt-3 flex items-start gap-1.5 pl-1.5">
              <Share2 size={13} className="text-cyan-500 mt-0.5 shrink-0" />
              <span>{t('llm_embedder_note')}</span>
            </p>
          </div>
        </>
      )}

      {/* Drawer */}
      {drawer && (
        <ProviderDrawer
          kind={drawer.kind}
          editing={!!drawer.editingId}
          providers={providers}
          form={form}
          saving={saving}
          canSave={canSave}
          existingEmbedder={
            embedder && embedder.provider
              ? { provider: embedder.provider, model: embedder.model }
              : null
          }
          onPickProvider={pickProvider}
          onName={(v) =>
            setForm((f) => (f ? { ...f, name: v } : { name: v, provider: '', model: '', values: {} }))
          }
          onModel={(v) => setForm((f) => (f ? { ...f, model: v } : f))}
          onValue={setValue}
          onClose={closeDrawer}
          onSave={save}
        />
      )}

      {/* Delete confirm */}
      {pendingDelete && (
        <ConfirmDelete
          conn={pendingDelete}
          isActive={active === pendingDelete.id}
          onCancel={() => setPendingDelete(null)}
          onConfirm={confirmDelete}
        />
      )}
    </div>
  )
}

function ProviderDrawer({
  kind,
  editing,
  providers,
  form,
  saving,
  canSave,
  existingEmbedder,
  onPickProvider,
  onName,
  onModel,
  onValue,
  onClose,
  onSave,
}: {
  kind: 'conn' | 'emb'
  editing: boolean
  providers: ProviderSpec[]
  form: FormState | null
  saving: boolean
  canSave: boolean
  existingEmbedder: { provider: string; model: string } | null
  onPickProvider: (id: string) => void
  onName: (v: string) => void
  onModel: (v: string) => void
  onValue: (name: string, v: string) => void
  onClose: () => void
  onSave: () => void
}) {
  const { t } = useTranslation()
  const [ack, setAck] = useState(false)
  const isEmb = kind === 'emb'
  const spec = form ? providers.find((p) => p.id === form.provider) : undefined

  const title = isEmb
    ? t('llm_drawer_edit_emb_title')
    : editing
      ? t('llm_drawer_edit_conn_title')
      : t('llm_drawer_add_conn_title')

  const desc = isEmb
    ? t('llm_drawer_emb_desc')
    : editing
      ? t('llm_drawer_edit_desc')
      : t('llm_drawer_add_desc')

  const modelList = form ? MODEL_SUGGESTIONS[form.provider] ?? [] : []

  const sharedEmbedder = isEmb && !!existingEmbedder?.provider
  const vectorSpaceChanged =
    sharedEmbedder &&
    !!form &&
    (form.provider !== existingEmbedder!.provider ||
      form.model.trim() !== (existingEmbedder!.model || ''))

  return (
    <>
      <div className="fixed inset-0 bg-slate-900/40 z-40" onClick={onClose} />
      <aside className="fixed top-0 right-0 bottom-0 w-full max-w-lg bg-white shadow-2xl z-50 flex flex-col">
        <div className="flex items-start justify-between px-6 py-5 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
            <p className="text-xs text-slate-500 mt-0.5">{desc}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 p-1 rounded hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {/* Embedder change safety — credential rotation (no space change) */}
          {sharedEmbedder && !vectorSpaceChanged && (
            <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-xs text-amber-800">
              <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-500" />
              <span>{t('llm_emb_shared_warn')}</span>
            </div>
          )}
          {/* Embedder vector space changed */}
          {vectorSpaceChanged && (
            <div className="mb-4 rounded-lg border border-red-300 bg-red-50 px-3.5 py-3 text-xs text-red-800">
              <div className="flex items-start gap-2.5">
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-red-600" />
                <div>
                  <p className="font-bold text-red-900 text-[13px] mb-1">{t('llm_vector_space_title')}</p>
                  <p className="leading-relaxed">{t('llm_vector_space_body')}</p>
                  <label className="mt-2.5 flex items-center gap-2 font-medium text-red-900 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={ack}
                      onChange={(e) => setAck(e.target.checked)}
                      className="rounded border-red-300 text-red-600 focus:ring-red-500"
                    />
                    {t('llm_vector_space_ack')}
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* Step 1: provider */}
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2.5 flex items-center gap-2">
            <span className="w-4 h-4 rounded-full bg-indigo-600 text-white text-[10px] font-bold flex items-center justify-center">
              1
            </span>
            {t('llm_step_provider')}
          </div>
          <div className="grid grid-cols-3 gap-2 mb-6">
            {providers.map((p) => {
              const m = meta(p.id)
              const sel = form?.provider === p.id
              return (
                <button
                  key={p.id}
                  onClick={() => onPickProvider(p.id)}
                  className={cn(
                    'border rounded-lg p-2.5 flex flex-col items-center gap-2 transition-all',
                    sel
                      ? 'border-indigo-500 bg-indigo-50 ring-1 ring-indigo-500'
                      : 'border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/40',
                  )}
                >
                  <span
                    className="w-9 h-9 rounded-lg flex items-center justify-center text-xs font-bold"
                    style={{ backgroundColor: alpha(m.color), color: m.color }}
                  >
                    <ProviderLogo id={p.id} size={20} />
                  </span>
                  <span className="text-[11px] font-medium text-slate-700 leading-tight text-center">{p.label}</span>
                </button>
              )
            })}
          </div>

          {/* Step 2: details */}
          {form && spec && (
            <>
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-indigo-600 text-white text-[10px] font-bold flex items-center justify-center">
                  2
                </span>
                {isEmb ? t('llm_step_emb_details') : t('llm_step_conn_details')}
              </div>

              <div className="space-y-3.5">
                {!isEmb && (
                  <FieldWrapper label={t('llm_field_display_name')} required>
                    <input
                      value={form.name}
                      onChange={(e) => onName(e.target.value)}
                      placeholder="e.g. Bedrock Nova Pro (prod)"
                      className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                  </FieldWrapper>
                )}

                <FieldWrapper label={t('llm_field_model')} required>
                  <input
                    value={form.model}
                    onChange={(e) => onModel(e.target.value)}
                    list={`models-${form.provider}`}
                    placeholder={modelList[0] ?? 'model name'}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 font-mono placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                  <datalist id={`models-${form.provider}`}>
                    {modelList.map((mo) => (
                      <option key={mo} value={mo} />
                    ))}
                  </datalist>
                  <p className="mt-1 text-xs text-slate-400">
                    {t('llm_field_model_hint')}
                  </p>
                </FieldWrapper>

                {spec.fields.map((fld) => (
                  <DynamicField
                    key={fld.name}
                    fld={fld}
                    value={form.values[fld.name] ?? ''}
                    editing={editing || isEmb}
                    onChange={(v) => onValue(fld.name, v)}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        <div className="border-t border-slate-200 px-6 py-3.5 flex items-center justify-between bg-slate-50">
          <button onClick={onClose} className="text-sm text-slate-500 hover:text-slate-800 px-3 py-1.5 rounded hover:bg-slate-100">
            {t('common_cancel')}
          </button>
          <button
            onClick={onSave}
            disabled={!canSave || saving || (vectorSpaceChanged && !ack)}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 size={14} className="animate-spin" />}
            {isEmb ? t('llm_save_emb') : t('common_save_conn')}
          </button>
        </div>
      </aside>
    </>
  )
}

function FieldWrapper({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-700 mb-1">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  )
}

function DynamicField({
  fld,
  value,
  editing,
  onChange,
}: {
  fld: { name: string; sensitive: boolean }
  value: string
  editing: boolean
  onChange: (v: string) => void
}) {
  const { t } = useTranslation()
  const inputCls =
    'w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent'
  const hint = FIELD_HINTS[fld.name]

  return (
    <FieldWrapper label={labelFor(fld.name)}>
      <input
        type={fld.sensitive ? 'password' : 'text'}
        value={value}
        autoComplete={fld.sensitive ? 'new-password' : 'off'}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          fld.sensitive ? (editing ? t('common_sensitive_keep') : t('common_sensitive_enter')) : ''
        }
        className={cn(inputCls, fld.name === 'deployment_id' && 'font-mono')}
      />
      {fld.sensitive && (
        <span className="mt-1 inline-block text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          {t('common_encrypted')}
        </span>
      )}
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </FieldWrapper>
  )
}

function ConfirmDelete({
  conn,
  isActive,
  onCancel,
  onConfirm,
}: {
  conn: LlmConnectionView
  isActive: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4" onClick={onCancel}>
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
        <div className="w-10 h-10 rounded-lg bg-red-50 text-red-600 flex items-center justify-center mb-3.5">
          <AlertTriangle size={20} />
        </div>
        <h3 className="text-base font-semibold text-slate-900 mb-1.5">
          {t('db_delete_title').replace('{name}', conn.name)}
        </h3>
        <p className="text-sm text-slate-500 mb-5">
          {isActive ? t('llm_delete_active_msg') : t('llm_delete_msg')}
        </p>
        <div className="flex justify-end gap-2.5">
          <button onClick={onCancel} className="text-sm text-slate-500 hover:text-slate-800 px-3.5 py-1.5 rounded hover:bg-slate-100">
            {t('common_cancel')}
          </button>
          <button onClick={onConfirm} className="px-4 py-1.5 rounded-md bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors">
            {t('common_delete')}
          </button>
        </div>
      </div>
    </div>
  )
}
