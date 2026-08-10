import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Server, RefreshCw, Save, Loader2, CheckCircle, XCircle, Zap } from 'lucide-react'
import { cn } from '@/lib/utils'
import { configApi, mcpApi } from '@/api/client'
import { useTranslation } from '@/hooks/useTranslation'

interface McpTestResult {
  ok: boolean
  status_code?: number
  message: string
}

export function McpServerPage() {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<McpTestResult | null>(null)
  const [mcpUrl, setMcpUrl] = useState('http://agenticai-mcp-service:4004')
  const [port, setPort] = useState('4004')

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const res = await configApi.get()
      const s4 = res.config.sap_s4hana as Record<string, unknown> | undefined
      if (s4?.mcp_url) setMcpUrl(String(s4.mcp_url))
      if (s4?.port) setPort(String(s4.port))
    } catch (err) {
      toast.error(`Failed to load: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  async function save() {
    setSaving(true)
    try {
      await configApi.save({
        sap_s4hana: {
          mcp_url: mcpUrl.trim().replace(/\/$/, ''),
          port: Number(port) || 4004,
        },
      })
      toast.success(t('mcp_toast_saved'))
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
      const res = await mcpApi.test()
      setTestResult(res)
      if (res.ok) toast.success(t('mcp_toast_reachable'))
      else toast.error(`MCP unreachable: ${res.message}`)
    } catch (err) {
      const msg = (err as Error).message
      setTestResult({ ok: false, message: msg })
      toast.error(msg)
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-lg bg-teal-50 border border-teal-200 flex items-center justify-center">
              <Server size={16} className="text-teal-600" />
            </div>
            <h1 className="text-lg font-semibold text-slate-900">{t('mcp_title')}</h1>
          </div>
          <p className="text-sm text-slate-500 ml-10">
            {t('mcp_desc')}
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

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-500 py-8">
          <Loader2 size={16} className="animate-spin" />
          {t('common_loading_config')}
        </div>
      ) : (
        <div className="space-y-5">
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50">
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                {t('mcp_section_settings')}
              </span>
            </div>
            <div className="px-5 py-5 space-y-4">
              <div>
                <label htmlFor="mcp-url" className="block text-xs font-medium text-slate-700 mb-1">
                  {t('mcp_field_url')}
                </label>
                <input
                  id="mcp-url"
                  type="text"
                  value={mcpUrl}
                  onChange={(e) => setMcpUrl(e.target.value)}
                  placeholder="http://agenticai-mcp-service:4004"
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 font-mono shadow-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                />
                <p className="mt-1 text-xs text-slate-400">
                  {t('mcp_url_hint')}
                </p>
              </div>
              <div className="w-32">
                <label htmlFor="mcp-port" className="block text-xs font-medium text-slate-700 mb-1">
                  {t('mcp_field_port')}
                </label>
                <input
                  id="mcp-port"
                  type="number"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  min={1000}
                  max={65535}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                />
              </div>
              <button
                onClick={save}
                disabled={saving}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-60 transition-colors"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {t('common_save')}
              </button>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50">
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                {t('mcp_section_test')}
              </span>
            </div>
            <div className="px-5 py-4">
              <p className="text-sm text-slate-500 mb-3">
                {t('mcp_test_desc')}
              </p>
              <button
                onClick={testConnection}
                disabled={testing}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-md border border-slate-300 text-slate-700 text-sm font-medium hover:bg-slate-50 disabled:opacity-50 transition-colors"
              >
                {testing ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                {testing ? t('common_testing') : t('mcp_btn_test')}
              </button>

              {testResult && (
                <div
                  className={cn(
                    'mt-3 flex items-start gap-2.5 rounded-lg px-4 py-3 text-sm border',
                    testResult.ok
                      ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                      : 'bg-red-50 border-red-200 text-red-800'
                  )}
                >
                  {testResult.ok ? (
                    <CheckCircle size={16} className="mt-0.5 shrink-0 text-emerald-600" />
                  ) : (
                    <XCircle size={16} className="mt-0.5 shrink-0 text-red-600" />
                  )}
                  <span>
                    {testResult.ok
                      ? testResult.status_code
                        ? t('mcp_test_ok').replace('{code}', String(testResult.status_code))
                        : t('mcp_test_ok_plain')
                      : testResult.message}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
