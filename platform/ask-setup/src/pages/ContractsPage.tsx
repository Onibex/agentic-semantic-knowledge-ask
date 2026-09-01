/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { FileCode, RefreshCw, Upload, Trash2, Loader2, ChevronDown, ChevronUp, CheckSquare, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { contractsApi, mcpApi } from '@/api/client'
import { useTranslation } from '@/hooks/useTranslation'
import type { ContractApi, ContractEntitySet, ContractsConfig } from '@/api/types'

// ── OpenAPI → ContractApi parser (JSON only) ─────────────────────────────────

function resolveRef(spec: Record<string, unknown>, schema: Record<string, unknown>, depth = 0): Record<string, unknown> {
  if (depth > 8 || !('$ref' in schema)) return schema
  const ref = schema.$ref as string
  const parts = ref.replace(/^#\//, '').split('/')
  let obj: unknown = spec
  for (const part of parts) {
    obj = (obj as Record<string, unknown>)?.[part]
  }
  return resolveRef(spec, (obj as Record<string, unknown>) ?? {}, depth + 1)
}

function extractFields(spec: Record<string, unknown>, schema: Record<string, unknown>) {
  const resolved = resolveRef(spec, schema)
  let properties: Record<string, unknown> = {}
  if ('allOf' in resolved && Array.isArray(resolved.allOf)) {
    for (const sub of resolved.allOf as Record<string, unknown>[]) {
      const r = resolveRef(spec, sub)
      Object.assign(properties, (r.properties as Record<string, unknown>) ?? {})
    }
  } else {
    properties = (resolved.properties as Record<string, unknown>) ?? {}
  }
  return Object.entries(properties).map(([fname, fschema]) => {
    const fs = resolveRef(spec, fschema as Record<string, unknown>)
    let ftype = (fs.type as string) || 'string'
    if (ftype === 'array') {
      const items = resolveRef(spec, (fs.items as Record<string, unknown>) ?? {})
      ftype = `array[${items.type ?? 'object'}]`
    }
    return {
      name: fname,
      type: ftype,
      description: ((fs.description ?? fs.title ?? '') as string).slice(0, 120),
      nullable: (fs.nullable as boolean) ?? true,
      maxLength: fs.maxLength as number | undefined,
      behavior: 'optional' as const,
    }
  })
}

function parseOpenApi(spec: Record<string, unknown>, filename: string): ContractApi | null {
  const info = (spec.info as Record<string, string>) ?? {}
  const paths = (spec.paths as Record<string, unknown>) ?? {}
  const servers = (spec.servers as Array<Record<string, string>>) ?? [{}]

  const serverUrl = servers[0]?.url ?? ''
  let pathPrefix = ''
  try {
    pathPrefix = new URL(serverUrl).pathname.replace(/\/$/, '')
  } catch { /* ignore */ }

  const rawName = info.title ?? filename.split('.')[0]
  const apiName = rawName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/, '').slice(0, 40)

  const entityMap: Record<string, {
    keys: { name: string; type: string }[]
    ops: Record<string, boolean>
    description: string
    fields: ReturnType<typeof extractFields>
  }> = {}

  for (const [path, pathItem] of Object.entries(paths)) {
    if (!pathItem || path.includes('$')) continue
    const m = path.match(/^\/([A-Za-z0-9_]+)/)
    if (!m) continue
    const entityName = m[1]
    if (!entityMap[entityName]) {
      entityMap[entityName] = {
        keys: [],
        ops: { list: false, get: false, create: false, update: false, delete: false },
        description: '',
        fields: [],
      }
    }
    const entry = entityMap[entityName]
    const keyM = path.match(/\(([^)]+)\)/)
    const hasKey = !!keyM
    if (keyM && !entry.keys.length) {
      const named = [...keyM[1].matchAll(/(\w+)='\{[^}]+\}'/g)].map((r) => r[1])
      entry.keys = named.length
        ? named.map((k) => ({ name: k, type: 'string' }))
        : [{ name: entityName, type: 'string' }]
    }
    for (const [method, op] of Object.entries(pathItem as Record<string, unknown>)) {
      if (!['get', 'post', 'patch', 'put', 'delete'].includes(method)) continue
      const opObj = op as Record<string, unknown>
      if (!entry.description) entry.description = String(opObj.summary ?? opObj.description ?? '').slice(0, 100)
      if (method === 'get') { if (hasKey) entry.ops.get = true; else entry.ops.list = true }
      else if (method === 'post') entry.ops.create = true
      else if (method === 'patch' || method === 'put') entry.ops.update = true
      else if (method === 'delete') entry.ops.delete = true
      if (['post', 'patch', 'put'].includes(method) && !entry.fields.length) {
        const rb = (opObj.requestBody as Record<string, unknown>) ?? {}
        const content = (rb.content as Record<string, unknown>) ?? {}
        const jsonContent = (content['application/json'] as Record<string, unknown>) ?? {}
        const schema = (jsonContent.schema as Record<string, unknown>) ?? {}
        if (Object.keys(schema).length) entry.fields = extractFields(spec, schema)
      }
    }
  }

  const entitySets: ContractEntitySet[] = Object.entries(entityMap).map(([name, data]) => ({
    entitySet: name,
    urlPath: name,
    description: data.description || name,
    category: apiName,
    keys: data.keys.length ? data.keys : [{ name, type: 'string' }],
    operations: data.ops,
    fields: data.fields,
  }))

  if (!entitySets.length) return null

  return {
    name: apiName,
    destination: 'SAP_S4_SALESORDER',
    pathPrefix,
    csrfProtected: true,
    entitySets,
    _meta: { title: info.title ?? '', version: info.version ?? '', filename },
  }
}

// ── Components ────────────────────────────────────────────────────────────────

const OP_LABELS: [string, string, string][] = [
  ['list', 'LIST', 'bg-blue-50 text-blue-700'],
  ['get', 'GET', 'bg-emerald-50 text-emerald-700'],
  ['create', 'POST', 'bg-amber-50 text-amber-700'],
  ['update', 'PATCH', 'bg-violet-50 text-violet-700'],
  ['delete', 'DEL', 'bg-red-50 text-red-700'],
]

function OpBadges({ ops }: { ops: Record<string, boolean | undefined> }) {
  return (
    <span className="flex flex-wrap gap-0.5">
      {OP_LABELS.filter(([k]) => ops[k]).map(([, label, cls]) => (
        <span key={label} className={cn('text-[10px] font-bold px-1.5 py-0.5 rounded', cls)}>
          {label}
        </span>
      ))}
    </span>
  )
}

function EntitySetsTable({ entitySets }: { entitySets: ContractEntitySet[] }) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-100">
            <th className="text-left pb-1.5 pr-3 font-semibold text-slate-500">{t('cont_table_entity_set')}</th>
            <th className="text-left pb-1.5 pr-3 font-semibold text-slate-500">{t('cont_table_operations')}</th>
            <th className="text-left pb-1.5 font-semibold text-slate-500">{t('cont_table_description')}</th>
          </tr>
        </thead>
        <tbody>
          {entitySets.map((es) => (
            <tr key={es.entitySet} className="border-b border-slate-50">
              <td className="py-1.5 pr-3 font-mono text-slate-700">{es.entitySet}</td>
              <td className="py-1.5 pr-3">
                <OpBadges ops={es.operations} />
              </td>
              <td className="py-1.5 text-slate-500">{es.description.slice(0, 60)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function ContractsPage() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<ContractsConfig>({ apis: [] })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [preview, setPreview] = useState<ContractApi | null>(null)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => { load() }, [])

  async function restartMcp() {
    setRestarting(true)
    try {
      const res = await mcpApi.restart()
      if (res.ok) {
        toast.success(res.message || 'MCP server restarted.')
      } else {
        toast.error(res.message || 'Restart failed.')
      }
    } catch (err) {
      toast.error(`Restart failed: ${(err as Error).message}`)
    } finally {
      setRestarting(false)
    }
  }

  async function load() {
    setLoading(true)
    try {
      const cfg = await contractsApi.get()
      setConfig(cfg)
    } catch (err) {
      toast.error(`Failed to load: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''

    const text = await file.text()
    let spec: Record<string, unknown>
    try {
      spec = JSON.parse(text)
    } catch {
      toast.error(t('cont_toast_json_only'))
      return
    }

    const parsed = parseOpenApi(spec, file.name)
    if (!parsed) {
      toast.error(t('cont_toast_no_entities'))
      return
    }
    setPreview(parsed)
    toast.success(
      t('cont_preview_entity_sets')
        .replace('{n}', String(parsed.entitySets.length))
        .replace('{filename}', parsed._meta?.filename || parsed.name)
    )
  }

  async function register() {
    if (!preview) return
    setSaving(true)
    try {
      const newApis = config.apis.filter((a) => a.name !== preview.name)
      newApis.push(preview)
      const newConfig: ContractsConfig = { ...config, apis: newApis }
      await contractsApi.save(newConfig)
      setConfig(newConfig)
      setPreview(null)
      toast.success(`${preview._meta?.title || preview.name} registered`)
    } catch (err) {
      toast.error(`Register failed: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  async function remove(name: string) {
    if (!confirm(t('cont_toast_remove_confirm').replace('{name}', name))) return
    setSaving(true)
    try {
      const newConfig: ContractsConfig = { ...config, apis: config.apis.filter((a) => a.name !== name) }
      await contractsApi.save(newConfig)
      setConfig(newConfig)
      toast.success(`${name} removed`)
    } catch (err) {
      toast.error(`Remove failed: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  const isBuiltin = (name: string) => name === 'salesorder'

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-lg bg-purple-50 border border-purple-200 flex items-center justify-center">
              <FileCode size={16} className="text-purple-600" />
            </div>
            <h1 className="text-lg font-semibold text-slate-900">{t('cont_title')}</h1>
          </div>
          <p className="text-sm text-slate-500 ml-10">
            {t('cont_desc')}
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 transition-colors py-1 px-2 rounded hover:bg-slate-100"
        >
          <RefreshCw size={13} className={cn(loading && 'animate-spin')} />
          {t('common_refresh')}
        </button>
      </div>

      {/* Upload */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden mb-5">
        <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
            {t('cont_section_upload')}
          </span>
        </div>
        <div className="px-5 py-5">
          <p className="text-sm text-slate-500 mb-3">
            {t('cont_upload_desc')}
          </p>
          <input ref={fileRef} type="file" accept=".json,application/json" className="hidden" onChange={handleFile} />
          <button
            onClick={() => fileRef.current?.click()}
            className="flex items-center gap-2 px-4 py-2 rounded-md border-2 border-dashed border-slate-300 text-sm text-slate-600 hover:border-indigo-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
          >
            <Upload size={15} />
            {t('cont_btn_choose')}
          </button>

          {preview && (
            <div className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50 overflow-hidden">
              <div className="px-4 py-3 bg-indigo-100 flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-indigo-900">
                    {preview._meta?.title || preview.name}
                  </p>
                  <p className="text-xs text-indigo-600 mt-0.5">
                    {t('cont_preview_entity_sets')
                      .replace('{n}', String(preview.entitySets.length))
                      .replace('{filename}', preview._meta?.filename || preview.name)}
                  </p>
                </div>
                {config.apis.some((a) => a.name === preview.name) && (
                  <span className="text-xs font-semibold text-amber-700 bg-amber-100 border border-amber-300 px-2 py-0.5 rounded">
                    {t('cont_preview_will_replace')}
                  </span>
                )}
              </div>
              <div className="px-4 py-3">
                <EntitySetsTable entitySets={preview.entitySets} />
              </div>
              <div className="px-4 py-3 border-t border-indigo-200 flex gap-2">
                <button
                  onClick={register}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-60 transition-colors"
                >
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckSquare size={14} />}
                  {t('cont_btn_register')}
                </button>
                <button
                  onClick={() => setPreview(null)}
                  className="px-4 py-1.5 rounded-md border border-slate-300 text-slate-600 text-sm font-medium hover:bg-slate-50 transition-colors"
                >
                  {t('common_cancel')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Registered contracts */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
            {t('cont_section_registered').replace('{n}', String(config.apis.length))}
          </span>
          <button
            onClick={restartMcp}
            disabled={restarting}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md border border-slate-300 text-slate-600 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title={t('cont_restart_tooltip')}
          >
            {restarting
              ? <Loader2 size={13} className="animate-spin" />
              : <RotateCcw size={13} />
            }
            {restarting ? t('cont_restarting') : t('cont_btn_restart')}
          </button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500 px-5 py-6">
            <Loader2 size={16} className="animate-spin" />
            {t('cont_loading')}
          </div>
        ) : config.apis.length === 0 ? (
          <p className="px-5 py-6 text-sm text-slate-400 italic">
            {t('cont_empty')}
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {config.apis.map((api, idx) => {
              const title = api._meta?.title || api.name
              const expanded = expandedIdx === idx
              const builtin = isBuiltin(api.name)
              return (
                <li key={api.name}>
                  <div className="px-5 py-3.5 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-sm font-semibold text-slate-800">{title}</span>
                        <span className={cn(
                          'text-[10px] font-semibold px-1.5 py-0.5 rounded border uppercase',
                          builtin
                            ? 'bg-blue-50 text-blue-700 border-blue-200'
                            : 'bg-violet-50 text-violet-700 border-violet-200'
                        )}>
                          {builtin ? t('cont_badge_builtin') : t('cont_badge_custom')}
                        </span>
                      </div>
                      <p className="text-xs font-mono text-slate-400">
                        {api.pathPrefix || '/'} · {api._meta?.filename || api.name}
                      </p>
                      <p className="text-xs text-slate-500 mt-0.5">
                        {t('cont_entity_count').replace('{n}', String(api.entitySets.length))}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => setExpandedIdx(expanded ? null : idx)}
                        className="text-slate-400 hover:text-slate-600 transition-colors p-1"
                      >
                        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                      {!builtin && (
                        <button
                          onClick={() => remove(api.name)}
                          disabled={saving}
                          className="text-slate-300 hover:text-red-500 transition-colors p-1"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                  {expanded && (
                    <div className="px-5 pb-4 border-t border-slate-50 pt-3">
                      <EntitySetsTable entitySets={api.entitySets} />
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
