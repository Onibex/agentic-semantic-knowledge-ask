import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import {
  Search,
  RefreshCw,
  Loader2,
  Zap,
  CheckCircle2,
  XCircle,
  Lock,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { setupApi } from '@/api/client'
import { useTranslation } from '@/hooks/useTranslation'
import type {
  SetupConfigField,
  SetupConfigSection,
  ConfigFieldSource,
  OpenSearchTestResponse,
} from '@/api/types'

// ── Field presentation ────────────────────────────────────────────────────────
const FIELD_LABELS: Record<string, string> = {
  host: 'Host',
  port: 'Port',
  use_ssl: 'SSL',
  embedding_dim: 'Embedding dimension',
  username: 'Username',
  password: 'Password',
}
function labelFor(f: SetupConfigField): string {
  return f.label ?? FIELD_LABELS[f.name] ?? f.name.replace(/_/g, ' ')
}

const MONO_FIELDS = new Set(['host', 'port', 'embedding_dim'])

const SOURCE_META: Record<ConfigFieldSource, { label: string; cls: string }> = {
  environment: { label: 'env', cls: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
  file: { label: 'file', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  encrypted: { label: 'encrypted', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
  plain: { label: 'config', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
  default: { label: 'default', cls: 'bg-slate-100 text-slate-400 border-slate-200' },
}

function SourceChip({ source }: { source: ConfigFieldSource }) {
  const m = SOURCE_META[source] ?? SOURCE_META.default
  return (
    <span className={cn('text-[9.5px] font-bold uppercase tracking-wide rounded px-1.5 py-0.5 border', m.cls)}>
      {m.label}
    </span>
  )
}

function ReadField({ field, notSetLabel }: { field: SetupConfigField; notSetLabel: string }) {
  const empty = !field.value
  return (
    <div>
      <dt className="text-[10.5px] font-semibold text-slate-500 uppercase tracking-wide mb-1">
        {labelFor(field)}
      </dt>
      <dd className={cn('text-sm text-slate-800 break-all flex items-center gap-2 flex-wrap', MONO_FIELDS.has(field.name) && 'font-mono text-slate-700')}>
        {empty ? <span className="text-slate-400 italic">{notSetLabel}</span> : field.value}
        <SourceChip source={field.source} />
      </dd>
    </div>
  )
}

export function SetupPage() {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [section, setSection] = useState<SetupConfigSection | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<OpenSearchTestResponse | null>(null)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setTestResult(null)
    try {
      const res = await setupApi.effective()
      setSection(res.sections.find((s) => s.id === 'opensearch') ?? null)
    } catch (err) {
      toast.error(`Failed to load: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  async function runTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await setupApi.testOpensearch()
      setTestResult(res)
      if (res.success) toast.success(`OpenSearch ${res.status || 'reachable'} (${res.latency_ms} ms)`)
      else toast.error(`OpenSearch: ${res.error ?? res.detail}`)
    } finally {
      setTesting(false)
    }
  }

  function testResultLabel(res: OpenSearchTestResponse): string {
    if (res.success) {
      const status = res.status || 'reachable'
      const ms = String(res.latency_ms)
      if (res.cluster_name) {
        return t('setup_result_ok')
          .replace('{name}', res.cluster_name)
          .replace('{status}', status)
          .replace('{ms}', ms)
      }
      return t('setup_result_ok_unnamed')
        .replace('{status}', status)
        .replace('{ms}', ms)
    }
    return res.error ?? res.detail ?? t('setup_result_fail')
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-200 flex items-center justify-center">
              <Search size={16} className="text-indigo-600" />
            </div>
            <h1 className="text-lg font-semibold text-slate-900">{t('setup_title')}</h1>
          </div>
          <p className="text-sm text-slate-500 ml-10 max-w-xl">{t('setup_desc')}</p>
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

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-500 py-8">
          <Loader2 size={16} className="animate-spin" />
          {t('common_loading_config')}
        </div>
      ) : (
        <>
          {/* OpenSearch connection (read-only) */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                {t('setup_section_connection')}
              </span>
              <span className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
                <Lock size={11} />
                {t('setup_section_managed')}
              </span>
            </div>
            <div className="px-5 py-5">
              {section && section.fields.length > 0 ? (
                <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {section.fields.map((f) => (
                    <ReadField key={f.name} field={f} notSetLabel={t('common_not_set')} />
                  ))}
                </dl>
              ) : (
                <p className="text-sm text-slate-400 italic">{t('setup_empty')}</p>
              )}

              {/* Env-management callout */}
              <div className="mt-5 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 leading-relaxed">
                <Lock size={14} className="mt-0.5 shrink-0 text-amber-500" />
                <div>
                  {t('setup_callout')}{' '}
                  <code className="font-mono bg-amber-100/70 px-1 rounded">.env</code>{' '}
                  {t('setup_callout_dev')}{' '}
                  <code className="font-mono bg-amber-100/70 px-1 rounded">OPENSEARCH_HOST</code>,{' '}
                  <code className="font-mono bg-amber-100/70 px-1 rounded">OPENSEARCH_PORT</code>,{' '}
                  <code className="font-mono bg-amber-100/70 px-1 rounded">OPENSEARCH_USE_SSL</code>,{' '}
                  <code className="font-mono bg-amber-100/70 px-1 rounded">OPENSEARCH_USER</code>,{' '}
                  <code className="font-mono bg-amber-100/70 px-1 rounded">OPENSEARCH_PASSWORD</code>.{' '}
                  {t('setup_callout_restart')}
                </div>
              </div>
            </div>
          </div>

          {/* Health check */}
          <div className="mt-4 bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50">
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                {t('setup_section_health')}
              </span>
            </div>
            <div className="px-5 py-4">
              <p className="text-sm text-slate-500 mb-3">{t('setup_health_desc')}</p>
              <button
                onClick={runTest}
                disabled={testing}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-md border border-slate-300 text-slate-700 text-sm font-medium hover:bg-slate-50 disabled:opacity-50 transition-colors"
              >
                {testing ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                {testing ? t('common_testing') : t('setup_btn_test')}
              </button>

              {testResult && (
                <div className={cn('mt-3 flex items-start gap-2.5 rounded-lg px-4 py-3 text-sm border',
                  testResult.success
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                    : 'bg-red-50 border-red-200 text-red-800',
                )}>
                  {testResult.success
                    ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" />
                    : <XCircle size={16} className="mt-0.5 shrink-0 text-red-600" />}
                  <span>{testResultLabel(testResult)}</span>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
