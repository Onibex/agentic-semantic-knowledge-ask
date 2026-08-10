import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { toast } from 'sonner'
import { LoadingState, ErrorState } from '@/lib/form-helpers'
import { getContracts, saveContracts } from '@/api/client'
import type { ContractsConfig } from '@/api/types'

// ── API card types ────────────────────────────────────────────────────────────

interface EntitySet {
  name?: string
  operations?: Record<string, boolean>
}

interface ApiEntry {
  name?: string
  destination?: string
  pathPrefix?: string
  entitySets?: EntitySet[]
}

function parseApiEntry(raw: unknown): ApiEntry {
  if (typeof raw !== 'object' || raw === null) return {}
  return raw as ApiEntry
}

function aggregateOps(entitySets: EntitySet[]): Record<string, boolean> {
  const ops: Record<string, boolean> = {}
  for (const es of entitySets) {
    for (const [k, v] of Object.entries(es.operations ?? {})) {
      if (v) ops[k] = true
    }
  }
  return ops
}

// ── Operation badge colors ────────────────────────────────────────────────────

const OP_COLORS: Record<string, string> = {
  list: 'bg-blue-100 text-blue-800',
  get: 'bg-purple-100 text-purple-800',
  create: 'bg-green-100 text-green-800',
  update: 'bg-yellow-100 text-yellow-800',
  delete: 'bg-red-100 text-red-800',
}

function OpChip({ op }: { op: string }) {
  const cls = OP_COLORS[op] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{op}</span>
  )
}

// ── API Summary Card ──────────────────────────────────────────────────────────

function ApiCard({ api }: { api: ApiEntry }) {
  const entitySets = api.entitySets ?? []
  const ops = aggregateOps(entitySets)
  const enabledOps = Object.keys(ops).filter((k) => ops[k])

  return (
    <div className="rounded-md border px-4 py-3 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-semibold text-sm text-gray-900">{api.name ?? '(unnamed)'}</span>
        {api.destination && (
          <Badge variant="secondary" className="text-xs">
            {api.destination}
          </Badge>
        )}
      </div>
      {api.pathPrefix && (
        <p className="font-mono text-xs text-gray-600">{api.pathPrefix}</p>
      )}
      <p className="text-xs text-gray-400">
        {entitySets.length} entity set{entitySets.length !== 1 ? 's' : ''}
      </p>
      {enabledOps.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-0.5">
          {enabledOps.map((op) => (
            <OpChip key={op} op={op} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ContractsPage() {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const [config, setConfig] = useState<ContractsConfig | null>(null)
  const [rawJson, setRawJson] = useState('')
  const [jsonValid, setJsonValid] = useState<boolean | null>(null)

  useEffect(() => {
    void loadContracts()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function loadContracts() {
    setLoading(true)
    setLoadError(null)
    try {
      const cfg = await getContracts()
      setConfig(cfg)
      setRawJson(JSON.stringify(cfg, null, 2))
      setJsonValid(true)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error loading contracts'
      setLoadError(msg)
    } finally {
      setLoading(false)
    }
  }

  function handleJsonChange(value: string) {
    setRawJson(value)
    try {
      JSON.parse(value)
      setJsonValid(true)
    } catch {
      setJsonValid(false)
    }
  }

  async function handleSave() {
    let parsed: ContractsConfig
    try {
      parsed = JSON.parse(rawJson) as ContractsConfig
    } catch {
      toast.error('Invalid JSON — fix before saving.')
      return
    }

    setSaving(true)
    try {
      const result = await saveContracts(parsed)
      if (result.success) {
        setConfig(parsed)
        toast.success('Contracts saved successfully')
      } else {
        toast.error(result.message ?? 'Error saving contracts')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Error saving contracts'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return <LoadingState label="Loading contracts…" />
  }

  if (loadError) {
    return (
      <ErrorState
        title="Error loading contracts"
        message={loadError}
        onRetry={() => void loadContracts()}
      />
    )
  }

  const apis = (config?.apis ?? []) as unknown[]

  return (
    <div className="p-8 max-w-4xl">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Contracts</h1>
        <p className="text-sm text-gray-500 mt-1">
          Manage OpenAPI contracts and MCP tools registry.
        </p>
      </div>

      {/* Summary Cards */}
      {apis.length > 0 && (
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">
            APIs ({apis.length})
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {apis.map((raw, i) => {
              const api = parseApiEntry(raw)
              return <ApiCard key={api.name ?? i} api={api} />
            })}
          </div>
        </div>
      )}

      {apis.length === 0 && config !== null && (
        <div className="mb-8 rounded-md border border-dashed px-4 py-6 text-center text-sm text-gray-400">
          No APIs configured yet. Add them via the JSON editor below.
        </div>
      )}

      {/* JSON Editor */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
            JSON Editor
          </h2>
          {jsonValid === true && (
            <span className="text-xs font-medium text-green-600">Valid JSON</span>
          )}
          {jsonValid === false && (
            <span className="text-xs font-medium text-red-600">Invalid JSON</span>
          )}
        </div>
        <textarea
          value={rawJson}
          onChange={(e) => handleJsonChange(e.target.value)}
          spellCheck={false}
          className="w-full rounded-md border bg-gray-50 px-3 py-2.5 font-mono text-xs text-gray-800 leading-relaxed focus:outline-none focus:ring-2 focus:ring-gray-300 resize-y"
          rows={20}
        />
      </div>

      {/* Save button */}
      <div className="mt-4">
        <Button
          onClick={() => void handleSave()}
          disabled={saving || jsonValid === false}
          className="min-w-40"
        >
          {saving ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Saving…
            </>
          ) : (
            'Save Contracts'
          )}
        </Button>
      </div>
    </div>
  )
}
