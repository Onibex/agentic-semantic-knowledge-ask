/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

﻿import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from '@/hooks/useTranslation'
import {
  Database,
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
  Upload,
  Circle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { dbApi } from '@/api/client'
import type {
  DbProviderSpec,
  DbProviderFieldSpec,
  DbConnectionView,
  DbActiveView,
} from '@/api/types'

// ── Cosmetic engine metadata (monogram + brand colour). The field schema and
//    labels come from the backend registry (/db/providers) — this map only adds
//    the visual identity that has no home in the registry. ────────────────────
const ENGINE_META: Record<string, { mono: string; color: string }> = {
  postgresql: { mono: 'PG', color: '#3d7ab5' },
  hana: { mono: 'HA', color: '#1a8fd6' },
  snowflake: { mono: 'SF', color: '#29b5e8' },
  databricks: { mono: 'DX', color: '#ee4b2e' },
  bigquery: { mono: 'BQ', color: '#4285f4' },
  clickhouse: { mono: 'CH', color: '#c79000' },
  sqlserver: { mono: 'MS', color: '#b7413a' },
  db2: { mono: 'D2', color: '#3557c7' },
  fabric: { mono: 'FB', color: '#12a37f' },
  presto: { mono: 'PR', color: '#5890ff' },
}
function meta(dbType: string) {
  return ENGINE_META[dbType] ?? { mono: dbType.slice(0, 2).toUpperCase(), color: '#64748b' }
}

// UI-side affordances keyed by field name (backend gives name/sensitive/kind only).
const SELECT_OPTIONS: Record<string, string[]> = {
  sslmode: ['prefer', 'disable', 'require', 'allow'],
  encrypt: ['yes', 'no'],
  trust_server_certificate: ['no', 'yes'],
  security: ['', 'SSL'],
  http_scheme: ['https', 'http'],
}
const FILE_FIELDS = new Set(['credentials_json'])
const FIELD_HINTS: Record<string, string> = {
  account: 'e.g. xy12345.eu-central-1',
  server_hostname: 'e.g. dbc-xxxx.cloud.databricks.com',
  http_path: 'e.g. /sql/1.0/warehouses/abc123',
  credentials_json: 'Upload the service-account JSON key file',
  private_key_file: 'Path to the .p8 key file on the server',
}
const MONO_FIELDS = new Set(['host', 'server', 'server_hostname', 'http_path', 'account'])

function labelFor(name: string): string {
  const map: Record<string, string> = {
    host: 'Host',
    port: 'Port',
    database: 'Database',
    user: 'User',
    username: 'Username',
    password: 'Password',
    sslmode: 'SSL mode',
    schema: 'Schema',
    account: 'Account',
    warehouse: 'Warehouse',
    role: 'Role',
    private_key_file: 'Private key file (path)',
    server_hostname: 'Server hostname',
    http_path: 'HTTP path',
    access_token: 'Access token',
    catalog: 'Catalog',
    secure: 'Secure (TLS)',
    final: 'FINAL modifier',
    driver: 'ODBC driver',
    encrypt: 'Encrypt',
    trust_server_certificate: 'Trust server certificate',
    security: 'Security',
    project: 'Project ID',
    credentials_path: 'Credentials path (ADC)',
    credentials_json: 'Service account key (JSON)',
    dataset: 'Dataset',
    location: 'Location',
    maximum_bytes_billed: 'Max bytes billed',
    server: 'SQL endpoint',
    tenant_id: 'Tenant ID',
    client_id: 'Client ID',
    client_secret: 'Client secret',
    http_scheme: 'HTTP scheme',
  }
  return map[name] ?? name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// Short one-line summary of a connection's target, shown on cards + the env bar.
function summarize(conn: DbConnectionView): string {
  const f: Record<string, string> = {}
  for (const row of conn.fields) f[row.name] = row.value
  switch (conn.db_type) {
    case 'snowflake':
      return `${f.account || '—'} · ${f.warehouse || '?'}/${f.database || '?'}`
    case 'databricks':
      return `${f.server_hostname || '—'} · ${f.catalog || '?'}.${f.schema || '?'}`
    case 'bigquery':
      return `${f.project || '—'} · ${f.dataset || '?'}`
    case 'fabric':
      return `${f.server || '—'} · ${f.database || '?'}`
    case 'presto':
      return `${f.host || '—'} · ${f.catalog || '?'}.${f.schema || '?'}`
    default: {
      const loc = f.database || f.schema || ''
      return `${f.host || '—'}:${f.port || '?'}${loc ? ' / ' + loc : ''}`
    }
  }
}

interface FormState {
  name: string
  dbType: string
  values: Record<string, string> // string values; toggles stored as 'true'/'false'
}

export function DatabasePage() {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [providers, setProviders] = useState<DbProviderSpec[]>([])
  const [connections, setConnections] = useState<DbConnectionView[]>([])
  const [active, setActive] = useState<DbActiveView>({ dev: null, prod: null })

  // Drawer
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [saving, setSaving] = useState(false)

  // Per-card transient state
  const [testing, setTesting] = useState<Set<string>>(new Set())
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<DbConnectionView | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [fileTarget, setFileTarget] = useState<string | null>(null)

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
      const [prov, list] = await Promise.all([dbApi.providers(), dbApi.list()])
      setProviders(prov.providers)
      setConnections(list.connections)
      setActive(list.active)
    } catch (err) {
      toast.error(`Failed to load connections: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  const providerById = useMemo(() => {
    const m: Record<string, DbProviderSpec> = {}
    for (const p of providers) m[p.id] = p
    return m
  }, [providers])

  // ── Drawer open/close ──────────────────────────────────────
  function openAdd() {
    setEditingId(null)
    setForm(null)
    setDrawerOpen(true)
  }

  function openEdit(conn: DbConnectionView) {
    const spec = providerById[conn.db_type]
    const values: Record<string, string> = {}
    if (spec) {
      for (const fld of spec.fields) {
        const row = conn.fields.find((r) => r.name === fld.name)
        // Sensitive fields come back blank (encrypted) — leave blank to keep.
        values[fld.name] = fld.sensitive ? '' : row?.value ?? ''
      }
    }
    setEditingId(conn.id)
    setForm({ name: conn.name, dbType: conn.db_type, values })
    setDrawerOpen(true)
  }

  function pickEngine(dbType: string) {
    const spec = providerById[dbType]
    const values: Record<string, string> = {}
    if (spec) {
      for (const fld of spec.fields) {
        values[fld.name] = fld.kind === 'bool' ? 'false' : ''
      }
    }
    setForm({ name: form?.name ?? '', dbType, values })
  }

  function closeDrawer() {
    setDrawerOpen(false)
    setEditingId(null)
    setForm(null)
  }

  function setValue(name: string, value: string) {
    setForm((f) => (f ? { ...f, values: { ...f.values, [name]: value } } : f))
  }

  // ── File upload for JSON key fields ────────────────────────
  function triggerFile(name: string) {
    setFileTarget(name)
    fileInputRef.current?.click()
  }
  async function onFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file
    if (!file || !fileTarget) return
    try {
      const text = await file.text()
      setValue(fileTarget, text)
      toast.success(`Loaded ${file.name}`)
    } catch {
      toast.error('Could not read file')
    }
  }

  const canSave = !!form && !!form.name.trim() && !!form.dbType

  async function save() {
    if (!form) return
    setSaving(true)
    try {
      const fields: Record<string, string> = { ...form.values }
      const body = { name: form.name.trim(), db_type: form.dbType, fields }
      if (editingId) {
        await dbApi.update(editingId, body)
        toast.success(`Saved "${body.name}"`)
      } else {
        await dbApi.create(body)
        toast.success(`Added "${body.name}"`)
      }
      closeDrawer()
      await load()
    } catch (err) {
      toast.error(`Save failed: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  // ── Card actions ───────────────────────────────────────────
  async function runTest(conn: DbConnectionView) {
    setTesting((s) => new Set(s).add(conn.id))
    try {
      const res = await dbApi.test(conn.id)
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

  async function setActiveFor(env: 'dev' | 'prod', id: string | null) {
    const next = { ...active, [env]: id }
    setActive(next)
    try {
      const res = await dbApi.setActive({ dev: next.dev, prod: next.prod })
      setActive(res)
      if (id) {
        const conn = connections.find((c) => c.id === id)
        toast.success(`${conn?.name ?? 'Connection'} active for ${env === 'dev' ? 'Development' : 'Production'}`)
      }
    } catch (err) {
      toast.error(`Could not update active: ${(err as Error).message}`)
      load()
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    const conn = pendingDelete
    setPendingDelete(null)
    try {
      await dbApi.remove(conn.id)
      toast.success(`Deleted "${conn.name}"`)
      await load()
    } catch (err) {
      toast.error(`Delete failed: ${(err as Error).message}`)
    }
  }

  // ── Render ─────────────────────────────────────────────────
  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center justify-center">
              <Database size={16} className="text-emerald-600" />
            </div>
            <h1 className="text-lg font-semibold text-slate-900">{t('db_title')}</h1>
          </div>
          <p className="text-sm text-slate-500 ml-10 max-w-xl">{t('db_desc')}</p>
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
            {t('db_btn_add')}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-500 py-10">
          <Loader2 size={16} className="animate-spin" />
          {t('db_loading')}
        </div>
      ) : (
        <>
          {/* Active per environment */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-7">
            {(['dev', 'prod'] as const).map((env) => {
              const id = active[env]
              const conn = connections.find((c) => c.id === id)
              const accent = env === 'dev' ? '#4f46e5' : '#7c3aed'
              return (
                <div
                  key={env}
                  className="relative bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3.5 overflow-hidden"
                >
                  <div className="absolute left-0 top-0 bottom-0 w-1" style={{ background: accent }} />
                  <div className="flex items-center justify-between mb-2.5 pl-1.5">
                    <span className="text-[11px] font-bold uppercase tracking-wider flex items-center gap-1.5" style={{ color: accent }}>
                      <Circle size={8} fill={accent} strokeWidth={0} />
                      {env === 'dev' ? t('common_development') : t('common_production')}
                      <span className="text-slate-400 font-semibold normal-case tracking-normal">{t('db_active_strip')}</span>
                    </span>
                    <select
                      value={id ?? ''}
                      onChange={(e) => setActiveFor(env, e.target.value || null)}
                      className="text-xs border border-slate-300 rounded-md px-2 py-1 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 max-w-[45%]"
                    >
                      <option value="">— none —</option>
                      {connections.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  {conn ? (
                    <div className="flex items-center gap-3 pl-1.5">
                      <div
                        className="w-9 h-9 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
                        style={{ backgroundColor: meta(conn.db_type).color + '22', color: meta(conn.db_type).color }}
                      >
                        {meta(conn.db_type).mono}
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-slate-800 truncate">{conn.name}</div>
                        <div className="text-xs text-slate-500 font-mono truncate">{summarize(conn)}</div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 pl-1.5 text-xs text-amber-600 font-medium">
                      <AlertTriangle size={14} />
                      {t('db_no_active_warn').replace('{env}', env)}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Connection list */}
          <div className="flex items-center justify-between mb-3 px-0.5">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">{t('db_section_all')}</h2>
            <span className="text-xs text-slate-400 font-semibold">{t('common_registered').replace('{n}', String(connections.length))}</span>
          </div>

          {connections.length === 0 ? (
            <div className="text-center py-14 border-2 border-dashed border-slate-200 rounded-xl bg-white">
              <div className="w-12 h-12 rounded-xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-3">
                <Database size={22} />
              </div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">{t('db_empty_title')}</h3>
              <p className="text-xs text-slate-500 mb-4">{t('db_empty_desc')}</p>
              <button
                onClick={openAdd}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
              >
                <Plus size={15} /> {t('db_btn_add')}
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
                    style={{ backgroundColor: meta(conn.db_type).color + '22', color: meta(conn.db_type).color }}
                  >
                    {meta(conn.db_type).mono}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-semibold text-slate-900">{conn.name}</span>
                      <span className="text-[11px] font-mono text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">
                        {conn.db_type}
                      </span>
                      {active.dev === conn.id && (
                        <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-indigo-50 text-indigo-700 border border-indigo-200">
                          {t('db_badge_active_dev')}
                        </span>
                      )}
                      {active.prod === conn.id && (
                        <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-violet-50 text-violet-700 border border-violet-200">
                          {t('db_badge_active_prod')}
                        </span>
                      )}
                      {!conn.configured && (
                        <span className="text-[11px] font-semibold rounded-full px-2 py-0.5 bg-amber-50 text-amber-700 border border-amber-200">
                          {t('common_incomplete')}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500 font-mono mt-1 truncate">{summarize(conn)}</div>
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
                          {t('db_set_active_for')}
                        </div>
                        {(['dev', 'prod'] as const).map((env) => (
                          <button
                            key={env}
                            onClick={() => {
                              setActiveFor(env, conn.id)
                              setMenuOpen(null)
                            }}
                            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm text-slate-700 hover:bg-slate-100 transition-colors"
                          >
                            <Circle size={8} fill={env === 'dev' ? '#4f46e5' : '#7c3aed'} strokeWidth={0} />
                            {env === 'dev' ? t('common_development') : t('common_production')}
                            {active[env] === conn.id && <Check size={14} className="ml-auto text-indigo-600" />}
                          </button>
                        ))}
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
        </>
      )}

      {/* Hidden file input for JSON key upload */}
      <input ref={fileInputRef} type="file" accept=".json,application/json" className="hidden" onChange={onFileChosen} />

      {/* Drawer */}
      {drawerOpen && (
        <ConnectionDrawer
          providers={providers}
          editing={!!editingId}
          form={form}
          saving={saving}
          canSave={canSave}
          onPickEngine={pickEngine}
          onName={(v) => setForm((f) => (f ? { ...f, name: v } : { name: v, dbType: '', values: {} }))}
          onValue={setValue}
          onUploadFile={triggerFile}
          onClose={closeDrawer}
          onSave={save}
        />
      )}

      {/* Delete confirm */}
      {pendingDelete && (
        <ConfirmDelete
          conn={pendingDelete}
          active={active}
          onCancel={() => setPendingDelete(null)}
          onConfirm={confirmDelete}
        />
      )}
    </div>
  )
}

// ── Drawer component ──────────────────────────────────────────
function ConnectionDrawer({
  providers,
  editing,
  form,
  saving,
  canSave,
  onPickEngine,
  onName,
  onValue,
  onUploadFile,
  onClose,
  onSave,
}: {
  providers: DbProviderSpec[]
  editing: boolean
  form: FormState | null
  saving: boolean
  canSave: boolean
  onPickEngine: (dbType: string) => void
  onName: (v: string) => void
  onValue: (name: string, v: string) => void
  onUploadFile: (name: string) => void
  onClose: () => void
  onSave: () => void
}) {
  const { t } = useTranslation()
  const spec = form ? providers.find((p) => p.id === form.dbType) : undefined
  return (
    <>
      <div className="fixed inset-0 bg-slate-900/40 z-40" onClick={onClose} />
      <aside className="fixed top-0 right-0 bottom-0 w-full max-w-lg bg-white shadow-2xl z-50 flex flex-col">
        <div className="flex items-start justify-between px-6 py-5 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {editing ? t('db_drawer_edit_title') : t('db_drawer_add_title')}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {editing ? t('common_update_details_desc') : t('db_drawer_add_desc')}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 p-1 rounded hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {/* Step 1: engine */}
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2.5 flex items-center gap-2">
            <span className="w-4 h-4 rounded-full bg-indigo-600 text-white text-[10px] font-bold flex items-center justify-center">
              1
            </span>
            {t('db_step_engine')}
          </div>
          <div className="grid grid-cols-3 gap-2 mb-6">
            {providers.map((p) => {
              const m = meta(p.id)
              const sel = form?.dbType === p.id
              return (
                <button
                  key={p.id}
                  disabled={editing}
                  onClick={() => onPickEngine(p.id)}
                  className={cn(
                    'border rounded-lg p-2.5 flex flex-col items-center gap-2 transition-all',
                    editing && 'opacity-50 cursor-default',
                    sel
                      ? 'border-indigo-500 bg-indigo-50 ring-1 ring-indigo-500'
                      : 'border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/40',
                  )}
                >
                  <span
                    className="w-9 h-9 rounded-lg flex items-center justify-center text-xs font-bold"
                    style={{ backgroundColor: m.color + '22', color: m.color }}
                  >
                    {m.mono}
                  </span>
                  <span className="text-[11px] font-medium text-slate-700 leading-tight text-center">{p.label}</span>
                </button>
              )
            })}
          </div>

          {/* Step 2: fields */}
          {form && spec && (
            <>
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-indigo-600 text-white text-[10px] font-bold flex items-center justify-center">
                  2
                </span>
                {t('db_step_conn_details')}
              </div>

              <div className="space-y-3.5">
                <Field label={t('common_display_name')} required>
                  <input
                    value={form.name}
                    onChange={(e) => onName(e.target.value)}
                    placeholder={t('db_field_name_ph')}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                </Field>

                {spec.fields.map((fld) => (
                  <DynamicField
                    key={fld.name}
                    fld={fld}
                    value={form.values[fld.name] ?? ''}
                    editing={editing}
                    onChange={(v) => onValue(fld.name, v)}
                    onUpload={() => onUploadFile(fld.name)}
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
            disabled={!canSave || saving}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 size={14} className="animate-spin" />}
            {t('common_save_conn')}
          </button>
        </div>
      </aside>
    </>
  )
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
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
  onUpload,
}: {
  fld: DbProviderFieldSpec
  value: string
  editing: boolean
  onChange: (v: string) => void
  onUpload: () => void
}) {
  const { t } = useTranslation()
  const inputCls =
    'w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent'
  const hint = FIELD_HINTS[fld.name]

  // Toggle (bool)
  if (fld.kind === 'bool') {
    const on = value === 'true'
    return (
      <div className="flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2 bg-slate-50">
        <span className="text-sm text-slate-700">{labelFor(fld.name)}</span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          onClick={() => onChange(on ? 'false' : 'true')}
          className={cn(
            'relative w-9 h-5 rounded-full transition-colors',
            on ? 'bg-indigo-600' : 'bg-slate-300',
          )}
        >
          <span
            className={cn(
              'absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
              on && 'translate-x-4',
            )}
          />
        </button>
      </div>
    )
  }

  // File upload (JSON key content)
  if (FILE_FIELDS.has(fld.name)) {
    const has = value.length > 0
    const keptOnServer = editing && !has
    return (
      <Field label={labelFor(fld.name)} required={!fld.sensitive}>
        <button
          type="button"
          onClick={onUpload}
          className={cn(
            'w-full flex items-center gap-3 border rounded-lg px-3 py-2.5 text-left transition-colors',
            has ? 'border-emerald-300 bg-emerald-50' : 'border-dashed border-slate-300 bg-slate-50 hover:border-indigo-400',
          )}
        >
          <span className={cn('w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border', has ? 'border-emerald-200 text-emerald-600 bg-white' : 'border-slate-200 text-indigo-600 bg-white')}>
            <Upload size={15} />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-medium text-slate-800">
              {has ? t('db_file_loaded') : keptOnServer ? t('db_file_on_server') : t('db_file_choose')}
            </span>
            <span className="block text-xs text-slate-500">
              {has ? t('db_file_encrypted') : keptOnServer ? t('db_file_keep') : hint ?? t('db_file_upload_hint')}
            </span>
          </span>
        </button>
      </Field>
    )
  }

  // Select (known option fields)
  if (SELECT_OPTIONS[fld.name]) {
    return (
      <Field label={labelFor(fld.name)}>
        <select value={value} onChange={(e) => onChange(e.target.value)} className={inputCls}>
          {SELECT_OPTIONS[fld.name].map((o) => (
            <option key={o} value={o}>
              {o === '' ? t('common_none_option') : o}
            </option>
          ))}
        </select>
      </Field>
    )
  }

  // Sensitive → password
  if (fld.sensitive) {
    return (
      <Field label={labelFor(fld.name)}>
        <input
          type="password"
          value={value}
          autoComplete="new-password"
          onChange={(e) => onChange(e.target.value)}
          placeholder={editing ? t('common_sensitive_keep') : t('common_sensitive_enter')}
          className={inputCls}
        />
        {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
      </Field>
    )
  }

  // Text / number
  return (
    <Field label={labelFor(fld.name)}>
      <input
        type={fld.kind === 'int' ? 'number' : 'text'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(inputCls, MONO_FIELDS.has(fld.name) && 'font-mono')}
      />
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </Field>
  )
}

// ── Delete confirm modal ──────────────────────────────────────
function ConfirmDelete({
  conn,
  active,
  onCancel,
  onConfirm,
}: {
  conn: DbConnectionView
  active: DbActiveView
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation()
  const isActive = active.dev === conn.id || active.prod === conn.id
  const envs = [active.dev === conn.id ? 'Dev' : null, active.prod === conn.id ? 'Prod' : null].filter(Boolean) as string[]
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
          {isActive
            ? t('db_delete_msg_active').replace('{envs}', envs.join(' and '))
            : t('db_delete_msg')}
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
