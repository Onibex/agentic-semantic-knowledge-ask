/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import {
  Plug,
  Pencil,
  X,
  Save,
  RefreshCw,
  CheckCircle,
  XCircle,
  Eye,
  EyeOff,
  Loader2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { sapApi } from '@/api/client'
import { useTranslation } from '@/hooks/useTranslation'
import type { SapConnectionConfig } from '@/api/types'

const MASK = '••••••••'
const DEFAULT_ODATA_PATH = '/sap/opu/odata/sap/API_SALES_ORDER_SRV'

interface FormState {
  host: string
  odata_path: string
  username: string
  password: string
}

function Field({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div>
      <dt className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-0.5">
        {label}
      </dt>
      <dd
        className={cn(
          'text-sm text-slate-800 break-all',
          mono && 'font-mono text-slate-700'
        )}
      >
        {value || <span className="text-slate-400 italic">{t('common_not_set')}</span>}
      </dd>
    </div>
  )
}

function Input({
  label,
  id,
  value,
  onChange,
  type = 'text',
  placeholder,
  hint,
}: {
  label: string
  id: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
  hint?: string
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-slate-700 mb-1">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
      />
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  )
}

export function SapConnectionPage() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<SapConnectionConfig | null>(null)
  const [editing, setEditing] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const [form, setForm] = useState<FormState>({
    host: '',
    odata_path: DEFAULT_ODATA_PATH,
    username: '',
    password: '',
  })

  useEffect(() => {
    load()
  }, [])

  async function load() {
    setLoading(true)
    try {
      const res = await sapApi.get()
      setConfig(res.config)
      setForm({
        host: res.config.host ?? '',
        odata_path: res.config.odata_path ?? DEFAULT_ODATA_PATH,
        username: res.config.username ?? '',
        password: '',
      })
    } catch (err) {
      toast.error(`Failed to load: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  function startEdit() {
    if (!config) return
    setForm({
      host: config.host ?? '',
      odata_path: config.odata_path ?? DEFAULT_ODATA_PATH,
      username: config.username ?? '',
      password: '',
    })
    setTestResult(null)
    setEditing(true)
  }

  function cancelEdit() {
    setEditing(false)
    setTestResult(null)
  }

  async function save() {
    if (!form.host.trim() || !form.username.trim()) {
      toast.error(t('sap_toast_required'))
      return
    }
    setSaving(true)
    try {
      const res = await sapApi.save({
        host: form.host.trim(),
        odata_path: form.odata_path.trim() || DEFAULT_ODATA_PATH,
        username: form.username.trim(),
        password: form.password || undefined,
      })
      setConfig(res.config)
      setEditing(false)
      toast.success(t('sap_toast_saved'))
    } catch (err) {
      toast.error(`Save failed: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  async function testConnection() {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await sapApi.test()
      setTestResult(result)
      if (result.success) {
        toast.success(t('sap_toast_success'))
      } else {
        toast.error(`Connection failed: ${result.message}`)
      }
    } catch (err) {
      const msg = (err as Error).message
      setTestResult({ success: false, message: msg })
      toast.error(msg)
    } finally {
      setTesting(false)
    }
  }

  function setField(field: keyof FormState) {
    return (v: string) => setForm((f) => ({ ...f, [field]: v }))
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center">
              <Plug size={16} className="text-blue-600" />
            </div>
            <h1 className="text-lg font-semibold text-slate-900">{t('sap_title')}</h1>
          </div>
          <p className="text-sm text-slate-500 ml-10">
            {t('sap_desc')}
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

      {/* Card */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {/* Card header */}
        <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between bg-slate-50">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
            {t('sap_section_details')}
          </span>
          {!editing && !loading && (
            <button
              onClick={startEdit}
              className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
            >
              <Pencil size={12} />
              {t('common_edit')}
            </button>
          )}
        </div>

        {/* Content */}
        <div className="px-5 py-5">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-slate-500 py-4">
              <Loader2 size={16} className="animate-spin" />
              {t('common_loading_config')}
            </div>
          ) : editing ? (
            /* Edit form */
            <div className="space-y-4">
              <Input
                label={t('sap_field_host')}
                id="host"
                value={form.host}
                onChange={setField('host')}
                placeholder={t('sap_ph_host')}
                hint={t('sap_host_hint')}
              />
              <Input
                label={t('sap_field_odata_path')}
                id="odata_path"
                value={form.odata_path}
                onChange={setField('odata_path')}
                placeholder={DEFAULT_ODATA_PATH}
              />
              <Input
                label={t('sap_field_username')}
                id="username"
                value={form.username}
                onChange={setField('username')}
                placeholder={t('sap_ph_username')}
              />
              <div>
                <label htmlFor="password" className="block text-xs font-medium text-slate-700 mb-1">
                  {t('sap_field_password')}
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={form.password}
                    onChange={(e) => setField('password')(e.target.value)}
                    placeholder={config?.password ? t('sap_ph_pw_keep') : t('sap_ph_pw_enter')}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 pr-9 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                {config?.password && (
                  <p className="mt-1 text-xs text-slate-400">
                    {t('sap_pw_hint_keep')}
                  </p>
                )}
              </div>

              {/* Form actions */}
              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={save}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-60 transition-colors"
                >
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  {t('common_save')}
                </button>
                <button
                  onClick={cancelEdit}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-md border border-slate-300 text-slate-700 text-sm font-medium hover:bg-slate-50 disabled:opacity-60 transition-colors"
                >
                  <X size={14} />
                  {t('common_cancel')}
                </button>
              </div>
            </div>
          ) : config ? (
            /* Read mode */
            <dl className="grid grid-cols-1 gap-4">
              <Field label={t('sap_field_host')} value={config.host} mono />
              <Field label={t('sap_field_odata_path')} value={config.odata_path} mono />
              <Field label={t('sap_field_username')} value={config.username} />
              <Field label={t('sap_field_password')} value={config.password ? MASK : ''} />
            </dl>
          ) : (
            <p className="text-sm text-slate-400 italic">{t('sap_no_config')}</p>
          )}
        </div>
      </div>

      {/* Test Connection */}
      <div className="mt-4 bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50">
          <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
            {t('sap_section_test')}
          </span>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm text-slate-500 mb-3">
            {t('sap_test_desc')}
          </p>

          <button
            onClick={testConnection}
            disabled={testing || loading || !config}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-md border border-slate-300 text-slate-700 text-sm font-medium hover:bg-slate-50 disabled:opacity-50 transition-colors"
          >
            {testing ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Plug size={14} />
            )}
            {testing ? t('common_testing') : t('sap_btn_test')}
          </button>

          {testResult && (
            <div
              className={cn(
                'mt-3 flex items-start gap-2.5 rounded-lg px-4 py-3 text-sm',
                testResult.success
                  ? 'bg-emerald-50 border border-emerald-200 text-emerald-800'
                  : 'bg-red-50 border border-red-200 text-red-800'
              )}
            >
              {testResult.success ? (
                <CheckCircle size={16} className="mt-0.5 shrink-0 text-emerald-600" />
              ) : (
                <XCircle size={16} className="mt-0.5 shrink-0 text-red-600" />
              )}
              <span>{testResult.message}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
