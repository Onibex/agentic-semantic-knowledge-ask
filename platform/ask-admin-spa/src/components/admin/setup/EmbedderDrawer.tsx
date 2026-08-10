import { AlertTriangle, Loader2, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { getSecrets, listSecretsProviders, putSecrets } from '@/api/client'
import type { ProviderSpec, SecretsGetResponse } from '@/api/types'

/**
 * Embedder editor — mirrors ASK Setup's embedder drawer (right-side panel,
 * registry-driven fields, the vector-space change warning) so the config
 * experience is identical across both apps. Writes the single shared
 * ``/v1/admin/secrets/embedder`` doc.
 */

const MODEL_SUGGESTIONS: Record<string, string[]> = {
  openai: ['text-embedding-3-large', 'text-embedding-3-small'],
  bedrock: ['amazon.titan-embed-text-v2:0'],
  gemini: ['gemini-embedding-001'],
  vertex_ai: ['text-embedding-004'],
  azure: ['text-embedding-3-large'],
  databricks: ['databricks-bge-large-en'],
  huggingface: ['sentence-transformers/all-MiniLM-L6-v2'],
  sap_aicore: ['text-embedding-3-large'],
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
function labelFor(name: string): string {
  return FIELD_LABELS[name] ?? name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

interface Props {
  open: boolean
  onSaved: () => void
  onClose: () => void
}

export function EmbedderDrawer({ open, onSaved, onClose }: Props) {
  const [providers, setProviders] = useState<ProviderSpec[]>([])
  const [current, setCurrent] = useState<SecretsGetResponse | null>(null)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [ack, setAck] = useState(false)

  const spec = useMemo(() => providers.find((p) => p.id === provider) ?? null, [providers, provider])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setAck(false)
    Promise.all([listSecretsProviders(), getSecrets('embedder')])
      .then(([list, cur]) => {
        if (cancelled) return
        setProviders(list.providers)
        setCurrent(cur)
        setProvider(cur.provider || '')
        setModel(cur.model || '')
        const seeded: Record<string, string> = {}
        for (const f of cur.fields) {
          if (!f.sensitive && f.value && f.value !== '***') seeded[f.name] = f.value
        }
        setValues(seeded)
      })
      .catch((err: unknown) => {
        toast.error(err instanceof Error ? err.message : 'Failed to load embedder')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open])

  function pickProvider(id: string) {
    setProvider(id)
    setValues({})
    setAck(false)
  }

  const hadEmbedder = !!current?.provider
  const vectorSpaceChanged =
    hadEmbedder && (provider !== (current?.provider ?? '') || model.trim() !== (current?.model ?? ''))

  const handleSave = useCallback(async () => {
    if (!provider) {
      toast.error('Pick a provider first')
      return
    }
    if (vectorSpaceChanged && !ack) {
      toast.error('Confirm the re-embedding warning before saving')
      return
    }
    setSaving(true)
    try {
      const payloadFields: Record<string, string> = {}
      for (const f of spec?.fields ?? []) {
        const v = values[f.name]
        if (f.sensitive) {
          if (v && v.length > 0) payloadFields[f.name] = v
        } else {
          payloadFields[f.name] = v ?? ''
        }
      }
      await putSecrets('embedder', { provider, model: model.trim(), fields: payloadFields })
      toast.success('Embedder saved — shared with ASK Setup')
      onSaved()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }, [provider, model, values, spec, vectorSpaceChanged, ack, onSaved, onClose])

  if (!open) return null

  const modelList = MODEL_SUGGESTIONS[provider] ?? []
  const canSave = !!provider && !(vectorSpaceChanged && !ack)

  return (
    <>
      <div className="fixed inset-0 bg-slate-900/40 z-40" onClick={saving ? undefined : onClose} />
      <aside className="fixed top-0 right-0 bottom-0 w-full max-w-lg bg-white shadow-2xl z-50 flex flex-col">
        <div className="flex items-start justify-between px-6 py-5 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Edit embedder</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Shared with ASK Setup — one embedder for the whole org. Blank secret fields keep the stored value.
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 p-1 rounded hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-slate-500 py-8">
              <Loader2 size={16} className="animate-spin" />
              Loading…
            </div>
          ) : (
            <>
              {/* Vector-space change safety */}
              {hadEmbedder && !vectorSpaceChanged && (
                <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-xs text-amber-800">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-500" />
                  <span>
                    This is the <b>single shared embedder</b> used across the platform (and ASK Setup).
                    Rotating credentials is safe; changing the <b>provider or model</b> redefines the vector space.
                  </span>
                </div>
              )}
              {vectorSpaceChanged && (
                <div className="mb-4 rounded-lg border border-red-300 bg-red-50 px-3.5 py-3 text-xs text-red-800">
                  <div className="flex items-start gap-2.5">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0 text-red-600" />
                    <div>
                      <p className="font-bold text-red-900 text-[13px] mb-1">This changes the embedding vector space</p>
                      <p className="leading-relaxed">
                        Every existing embedding — knowledge graph, semantic dictionary and docs, across
                        <b> dev and prod</b> — becomes incompatible and returns wrong or empty results until you
                        <b> re-ingest and re-embed everything</b>. Vector dimensions may differ, so the indices are
                        rebuilt from scratch. This is not automatic, and switching back won't restore rebuilt data.
                      </p>
                      <label className="mt-2.5 flex items-center gap-2 font-medium text-red-900 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={ack}
                          onChange={(e) => setAck(e.target.checked)}
                          className="rounded border-red-300 text-red-600 focus:ring-red-500"
                        />
                        I understand — I will re-ingest and re-embed all published data after saving.
                      </label>
                    </div>
                  </div>
                </div>
              )}

              {/* Provider */}
              <div className="mb-4">
                <label className="block text-xs font-medium text-slate-700 mb-1">Provider</label>
                <select
                  value={provider}
                  onChange={(e) => pickProvider(e.target.value)}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                >
                  <option value="">— Select provider —</option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>

              {spec && (
                <div className="space-y-3.5">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 mb-1">
                      Model<span className="text-red-500 ml-0.5">*</span>
                    </label>
                    <input
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      list="emb-models"
                      placeholder={modelList[0] ?? 'model name'}
                      className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 font-mono placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                    <datalist id="emb-models">
                      {modelList.map((m) => (
                        <option key={m} value={m} />
                      ))}
                    </datalist>
                    <p className="mt-1 text-xs text-slate-400">
                      Just the model id — the provider is already selected.
                    </p>
                  </div>

                  {spec.fields.map((f) => (
                    <div key={f.name}>
                      <label className="block text-xs font-medium text-slate-700 mb-1">
                        {labelFor(f.name)}
                        {f.sensitive && (
                          <span className="ml-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                            encrypted
                          </span>
                        )}
                      </label>
                      <input
                        type={f.sensitive ? 'password' : 'text'}
                        autoComplete={f.sensitive ? 'new-password' : 'off'}
                        value={values[f.name] ?? ''}
                        onChange={(e) => setValues((prev) => ({ ...prev, [f.name]: e.target.value }))}
                        placeholder={f.sensitive ? '•••••••• (leave blank to keep)' : ''}
                        className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                      />
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <div className="border-t border-slate-200 px-6 py-3.5 flex items-center justify-between bg-slate-50">
          <button onClick={onClose} className="text-sm text-slate-500 hover:text-slate-800 px-3 py-1.5 rounded hover:bg-slate-100">
            Cancel
          </button>
          <button
            onClick={() => void handleSave()}
            disabled={!canSave || saving || loading}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 size={14} className="animate-spin" />}
            Save embedder
          </button>
        </div>
      </aside>
    </>
  )
}
