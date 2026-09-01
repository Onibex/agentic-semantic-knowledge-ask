/*
 * SPDX-License-Identifier: LicenseRef-PolyForm-Strict-1.0.0 OR LicenseRef-PolyForm-Free-Trial-1.0.0
 * Copyright (c) 2026 Onibex, LLC. All rights reserved.
 *
 * Part of Onibex ASK — Agentic Semantic Knowledge.
 * Source-available under PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0.
 * Commercial licenses: contact@onibex.com — see LICENSE.
 */

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { LoadingState, ErrorState } from '@/lib/form-helpers'
import { getConfig, saveConfig, testMcpConnection } from '@/api/client'
import type { AppSettings, ConnectionTestResult } from '@/api/types'

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function McpPage() {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null)

  const [mcpUrl, setMcpUrl] = useState('')
  const [port, setPort] = useState(4004)

  useEffect(() => {
    void loadConfig()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function loadConfig() {
    setLoading(true)
    setLoadError(null)
    try {
      const cfg = await getConfig()
      setMcpUrl(cfg.sap_s4hana?.mcp_url ?? '')
      setPort(cfg.sap_s4hana?.port ?? 4004)
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
      const result = await testMcpConnection()
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
      const config: AppSettings = { sap_s4hana: { mcp_url: mcpUrl, port } }
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
    <div className="p-8 max-w-2xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">MCP Server</h1>
        <p className="text-sm text-gray-500 mt-1">
          Manage MCP server configuration and tool registrations.
        </p>
      </div>

      {/* Form */}
      <div className="rounded-md border p-6 space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="mcp-url">MCP Server URL</Label>
          <Input
            id="mcp-url"
            type="text"
            value={mcpUrl}
            onChange={(e) => setMcpUrl(e.target.value)}
            placeholder="http://ask-mcp:4004"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="mcp-port">Port</Label>
          <Input
            id="mcp-port"
            type="number"
            value={String(port)}
            onChange={(e) => setPort(Number(e.target.value) || 4004)}
            placeholder="4004"
          />
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
            className="min-w-48"
          >
            {testing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Testing…
              </>
            ) : (
              'Test MCP Connection'
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
        <Button onClick={() => void handleSave()} disabled={saving} className="min-w-28">
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Saving…
            </>
          ) : (
            'Save'
          )}
        </Button>
      </div>
    </div>
  )
}
