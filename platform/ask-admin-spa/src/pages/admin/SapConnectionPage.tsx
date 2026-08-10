import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { Field, cleanSection, LoadingState, ErrorState } from '@/lib/form-helpers'
import { getConfig, saveConfig, testSapConnection } from '@/api/client'
import type { AppSettings, ConnectionTestResult } from '@/api/types'

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SapConnectionPage() {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null)

  // Form fields
  const [host, setHost] = useState('')
  const [odataPath, setOdataPath] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [mcpUrl, setMcpUrl] = useState('')
  const [port, setPort] = useState(44300)

  useEffect(() => {
    void loadConfig()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function loadConfig() {
    setLoading(true)
    setLoadError(null)
    try {
      const cfg = await getConfig()
      setHost(cfg.sap_s4hana?.host ?? '')
      setOdataPath(cfg.sap_s4hana?.odata_path ?? '')
      setUsername(cfg.sap_s4hana?.username ?? '')
      setPassword('') // never pre-fill passwords
      setMcpUrl(cfg.sap_s4hana?.mcp_url ?? '')
      setPort(cfg.sap_s4hana?.port ?? 44300)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error loading configuration'
      setLoadError(msg)
    } finally {
      setLoading(false)
    }
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await testSapConnection()
      setTestResult(result)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Connection test failed'
      setTestResult({ ok: false, status_code: null, message: msg })
    } finally {
      setTesting(false)
    }
  }

  async function handleSave() {
    setSaving(true)
    try {
      const section = cleanSection(
        { host, odata_path: odataPath, username, password, mcp_url: mcpUrl, port },
        ['password'],
      )
      const config: AppSettings = { sap_s4hana: section }
      const result = await saveConfig(config)
      if (result.success) {
        toast.success('Configuration saved successfully')
      } else {
        toast.error(result.message ?? 'Error saving configuration')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error saving configuration'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return <LoadingState label="Loading configuration…" />
  }

  if (loadError) {
    return (
      <ErrorState
        title="Error loading configuration"
        message={loadError}
        onRetry={() => void loadConfig()}
      />
    )
  }

  return (
    <div className="p-8 max-w-3xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">SAP Connection</h1>
        <p className="text-sm text-gray-500 mt-1">
          Configure SAP S/4HANA system connection and credentials.
        </p>
      </div>

      {/* Form */}
      <div className="rounded-md border p-6 space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <Field
              id="sap-host"
              label="Host"
              value={host}
              onChange={setHost}
              placeholder="https://my-s4-host.example.com:44300"
            />
          </div>
          <div className="col-span-2">
            <Field
              id="sap-odata-path"
              label="OData path"
              value={odataPath}
              onChange={setOdataPath}
              placeholder="/sap/opu/odata/sap/API_SALES_ORDER_SRV"
            />
          </div>
          <Field
            id="sap-username"
            label="Username"
            value={username}
            onChange={setUsername}
            placeholder="SAP_USER"
          />
          <Field
            id="sap-password"
            label="Password"
            value={password}
            onChange={setPassword}
            placeholder="Leave blank to keep existing"
            type="password"
          />
          <div className="col-span-2">
            <Field
              id="sap-mcp-url"
              label="MCP Server URL"
              value={mcpUrl}
              onChange={setMcpUrl}
              placeholder="http://agenticai-mcp:4004"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sap-port">MCP Port</Label>
            <Input
              id="sap-port"
              type="number"
              value={String(port)}
              onChange={(e) => setPort(Number(e.target.value) || 44300)}
              placeholder="44300"
            />
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="mt-6 space-y-4">
        {/* Test button + inline result */}
        <div className="space-y-2">
          <Button
            variant="outline"
            onClick={() => void handleTest()}
            disabled={testing}
            className="min-w-52"
          >
            {testing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Testing…
              </>
            ) : (
              'Test SAP OData Connection'
            )}
          </Button>

          {testResult !== null && (
            <div
              className={`rounded-md px-4 py-2.5 text-sm max-w-lg ${
                testResult.ok
                  ? 'bg-green-50 border border-green-200 text-green-800'
                  : 'bg-red-50 border border-red-200 text-red-800'
              }`}
            >
              <span className="font-medium">{testResult.ok ? 'Connected' : 'Failed'}:</span>{' '}
              {testResult.message}
              {testResult.status_code !== null && (
                <span className="ml-2 text-xs opacity-70">(HTTP {testResult.status_code})</span>
              )}
            </div>
          )}
        </div>

        {/* Save button */}
        <Button onClick={() => void handleSave()} disabled={saving} className="min-w-44">
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Saving…
            </>
          ) : (
            'Save Configuration'
          )}
        </Button>
      </div>
    </div>
  )
}
