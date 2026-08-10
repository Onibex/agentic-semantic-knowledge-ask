import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import {
  BookMarked,
  RefreshCw,
  Loader2,
  Trash2,
  Plus,
  ChevronDown,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { dictionaryApi } from '@/api/client'
import type { DictionaryEntry, DictionaryListEntry } from '@/api/types'

const SAP_MODULES = ['SD', 'MM', 'PP', 'FI', 'CO']

const FIELD_TYPES = [
  { value: 'metric', label: 'Metric' },
  { value: 'dimension', label: 'Dimension' },
  { value: 'filter', label: 'Filter' },
  { value: 'identifier', label: 'Identifier' },
  { value: 'timestamp', label: 'Timestamp' },
]

const TYPE_FILTER_OPTIONS = [
  { value: 'phrase', label: 'Phrases' },
  { value: 'metric', label: 'Metrics' },
  { value: 'dimension', label: 'Dimensions' },
  { value: 'filter', label: 'Filters' },
  { value: 'identifier', label: 'Identifiers' },
]

type FormTab = 'field' | 'phrase'

interface FieldForm {
  canonical_label: string
  technical_name: string
  table: string
  field_type: string
  synonyms: string
  context_clues: string
  disambiguation_hint: string
  entity_id: string
  description: string
  examples: string
  value_synonyms: string
  is_preferred_id: boolean
}

interface PhraseForm {
  phrase: string
  cols: string
  synonyms: string
  context_clues: string
  entity_id: string
  description: string
}

function emptyField(): FieldForm {
  return {
    canonical_label: '', technical_name: '', table: '', field_type: 'metric',
    synonyms: '', context_clues: '', disambiguation_hint: '', entity_id: '',
    description: '', examples: '', value_synonyms: '', is_preferred_id: false,
  }
}

function emptyPhrase(): PhraseForm {
  return { phrase: '', cols: '', synonyms: '', context_clues: '', entity_id: '', description: '' }
}

function FormInput({
  label, value, onChange, placeholder, hint, type = 'text',
}: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; hint?: string; type?: string
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-700 mb-1">{label}</label>
      <input
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

function FormTextarea({
  label, value, onChange, placeholder, rows = 2,
}: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; rows?: number
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-700 mb-1">{label}</label>
      <textarea
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
      />
    </div>
  )
}

function typeColor(type: string) {
  switch (type) {
    case 'phrase': return 'bg-indigo-50 text-indigo-700 border-indigo-200'
    case 'metric': return 'bg-emerald-50 text-emerald-700 border-emerald-200'
    case 'dimension': return 'bg-blue-50 text-blue-700 border-blue-200'
    case 'filter': return 'bg-amber-50 text-amber-700 border-amber-200'
    case 'identifier': return 'bg-violet-50 text-violet-700 border-violet-200'
    case 'timestamp': return 'bg-slate-50 text-slate-600 border-slate-200'
    default: return 'bg-slate-50 text-slate-600 border-slate-200'
  }
}

export function SemanticAdminPage() {
  const [formTab, setFormTab] = useState<FormTab>('field')
  const [module, setModule] = useState('SD')
  const [sourceSystem, setSourceSystem] = useState('s4h')
  const [typeFilter, setTypeFilter] = useState('phrase')
  const [fieldForm, setFieldForm] = useState<FieldForm>(emptyField())
  const [phraseForm, setPhraseForm] = useState<PhraseForm>(emptyPhrase())
  const [entries, setEntries] = useState<DictionaryListEntry[]>([])
  const [loadingList, setLoadingList] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => { loadList() }, [module, typeFilter])

  async function loadList() {
    setLoadingList(true)
    try {
      const res = await dictionaryApi.list(module, typeFilter)
      setEntries(res.entries)
    } catch (err) {
      toast.error(`Failed to load entries: ${(err as Error).message}`)
    } finally {
      setLoadingList(false)
    }
  }

  async function saveField() {
    if (!fieldForm.canonical_label.trim() || !fieldForm.technical_name.trim()) {
      toast.error('Canonical Label and Technical Name are required')
      return
    }
    setSaving(true)
    try {
      const entry: DictionaryEntry = {
        type: fieldForm.field_type,
        canonical_label: fieldForm.canonical_label,
        technical_name: fieldForm.technical_name,
        table: fieldForm.table || undefined,
        synonyms: fieldForm.synonyms || undefined,
        context_clues: fieldForm.context_clues || undefined,
        disambiguation_hint: fieldForm.disambiguation_hint || undefined,
        module,
        source_system: sourceSystem,
        entity_id: fieldForm.entity_id || undefined,
        description: fieldForm.description || undefined,
        examples: fieldForm.examples || undefined,
        value_synonyms: fieldForm.value_synonyms || undefined,
        is_preferred_id: fieldForm.is_preferred_id,
      }
      const res = await dictionaryApi.upsert(entry)
      if (res.success) {
        toast.success(`'${fieldForm.canonical_label}' saved`)
        setFieldForm(emptyField())
        await loadList()
      } else {
        toast.error(res.message || 'Save failed')
      }
    } catch (err) {
      toast.error(`Save failed: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  async function savePhrase() {
    if (!phraseForm.phrase.trim() || !phraseForm.cols.trim()) {
      toast.error('Phrase and Columns are required')
      return
    }
    setSaving(true)
    try {
      const entry: DictionaryEntry = {
        type: 'phrase',
        canonical_label: phraseForm.phrase,
        technical_name: phraseForm.cols,
        synonyms: phraseForm.synonyms || undefined,
        context_clues: phraseForm.context_clues || undefined,
        module,
        source_system: sourceSystem,
        entity_id: phraseForm.entity_id || undefined,
        description: phraseForm.description || undefined,
      }
      const res = await dictionaryApi.upsert(entry)
      if (res.success) {
        toast.success(`Phrase '${phraseForm.phrase}' saved`)
        setPhraseForm(emptyPhrase())
        if (typeFilter === 'phrase') await loadList()
      } else {
        toast.error(res.message || 'Save failed')
      }
    } catch (err) {
      toast.error(`Save failed: ${(err as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  async function deleteEntry(id: string, label: string) {
    if (!confirm(`Remove "${label}"?`)) return
    setDeletingId(id)
    try {
      await dictionaryApi.delete(id)
      toast.success(`'${label}' removed`)
      setEntries((prev) => prev.filter((e) => e.id !== id))
    } catch (err) {
      toast.error(`Delete failed: ${(err as Error).message}`)
    } finally {
      setDeletingId(null)
    }
  }

  function setField(k: keyof FieldForm) {
    return (v: string | boolean) => setFieldForm((f) => ({ ...f, [k]: v }))
  }
  function setPhrase(k: keyof PhraseForm) {
    return (v: string) => setPhraseForm((f) => ({ ...f, [k]: v }))
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-lg bg-amber-50 border border-amber-200 flex items-center justify-center">
              <BookMarked size={16} className="text-amber-600" />
            </div>
            <h1 className="text-lg font-semibold text-slate-900">Semantic Dictionary</h1>
          </div>
          <p className="text-sm text-slate-500 ml-10">
            Manage business term mappings so the agent can resolve ambiguous queries
          </p>
        </div>
      </div>

      {/* Global filters */}
      <div className="flex items-center gap-3 mb-5">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">SAP Module</label>
          <div className="flex gap-1">
            {SAP_MODULES.map((m) => (
              <button
                key={m}
                onClick={() => setModule(m)}
                className={cn(
                  'px-3 py-1 rounded text-xs font-semibold border transition-colors',
                  module === m
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50'
                )}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Source System</label>
          <input
            value={sourceSystem}
            onChange={(e) => setSourceSystem(e.target.value)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 w-24"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-5">
        {/* ── LEFT: Editor ── */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-slate-200">
            {([['field', 'Field / Metric'], ['phrase', 'Phrase']] as const).map(([id, label]) => (
              <button
                key={id}
                onClick={() => setFormTab(id)}
                className={cn(
                  'flex-1 py-2.5 text-xs font-semibold uppercase tracking-wide transition-colors',
                  formTab === id
                    ? 'bg-white text-indigo-600 border-b-2 border-indigo-600'
                    : 'bg-slate-50 text-slate-500 hover:text-slate-700'
                )}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="px-4 py-4 space-y-3">
            {formTab === 'field' ? (
              <>
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">Type</label>
                  <select
                    value={fieldForm.field_type}
                    onChange={(e) => setField('field_type')(e.target.value)}
                    className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    {FIELD_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </div>
                <FormInput label="Canonical Label *" value={fieldForm.canonical_label} onChange={setField('canonical_label') as (v: string) => void} placeholder="e.g. Net Value" />
                <FormInput label="Technical Name (SAP Column) *" value={fieldForm.technical_name} onChange={setField('technical_name') as (v: string) => void} placeholder="e.g. NETWR" />
                <FormInput label="Table" value={fieldForm.table} onChange={setField('table') as (v: string) => void} placeholder="e.g. VBAP" />
                <FormInput label="Synonyms (comma-separated)" value={fieldForm.synonyms} onChange={setField('synonyms') as (v: string) => void} placeholder="e.g. revenue, sales amount" />
                <FormInput label="Context Clues (comma-separated)" value={fieldForm.context_clues} onChange={setField('context_clues') as (v: string) => void} placeholder="e.g. order, billing" />
                <FormTextarea label="Disambiguation Hint" value={fieldForm.disambiguation_hint} onChange={setField('disambiguation_hint') as (v: string) => void} placeholder="Use when referring to..." />
                <FormInput label="Silver Entity ID (optional)" value={fieldForm.entity_id} onChange={setField('entity_id') as (v: string) => void} placeholder="e.g. silver_s4h_sd_sales_order" />
                <FormTextarea label="Description" value={fieldForm.description} onChange={setField('description') as (v: string) => void} placeholder="What does this field represent?" />
                <details className="border border-slate-200 rounded-md">
                  <summary className="px-3 py-2 text-xs font-medium text-slate-600 cursor-pointer flex items-center gap-1.5">
                    <ChevronDown size={12} />
                    Value-level enrichments
                  </summary>
                  <div className="px-3 pb-3 space-y-3 border-t border-slate-100 pt-3">
                    <FormInput label="Examples (comma-separated)" value={fieldForm.examples} onChange={setField('examples') as (v: string) => void} placeholder="e.g. F226, Z, MAT-00145" hint="Typical values in this column" />
                    <FormInput label="Value Synonyms (user=actual, comma-sep)" value={fieldForm.value_synonyms} onChange={setField('value_synonyms') as (v: string) => void} placeholder="e.g. finalized=Completed, pending=Open" />
                    <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={fieldForm.is_preferred_id}
                        onChange={(e) => setField('is_preferred_id')(e.target.checked)}
                        className="rounded border-slate-300"
                      />
                      Mark as preferred ID column
                    </label>
                  </div>
                </details>
                <button
                  onClick={saveField}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-60 transition-colors w-full justify-center"
                >
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                  Save Field Mapping
                </button>
              </>
            ) : (
              <>
                <FormInput label="Phrase / Concept *" value={phraseForm.phrase} onChange={setPhrase('phrase')} placeholder="e.g. order header details" />
                <FormTextarea label="Semantic Fields / Columns *" value={phraseForm.cols} onChange={setPhrase('cols')} placeholder="e.g. document number, order item, KUNNR" />
                <FormInput label="Synonyms (comma-separated)" value={phraseForm.synonyms} onChange={setPhrase('synonyms')} placeholder="e.g. order info, detalle del pedido" />
                <FormInput label="Context Clues (comma-separated)" value={phraseForm.context_clues} onChange={setPhrase('context_clues')} placeholder="e.g. order, header, detail" />
                <FormInput label="Silver Entity ID (optional)" value={phraseForm.entity_id} onChange={setPhrase('entity_id')} placeholder="e.g. silver_s4h_sd_sales_order" />
                <FormTextarea label="Description" value={phraseForm.description} onChange={setPhrase('description')} placeholder="What does this phrase represent?" />
                <button
                  onClick={savePhrase}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-60 transition-colors w-full justify-center"
                >
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                  Save Phrase Mapping
                </button>
              </>
            )}
          </div>
        </div>

        {/* ── RIGHT: Entries viewer ── */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
              {module} Dictionary
            </span>
            <div className="flex items-center gap-2">
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="text-xs rounded border border-slate-300 bg-white px-2 py-1 text-slate-700 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {TYPE_FILTER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <button
                onClick={loadList}
                disabled={loadingList}
                className="text-slate-400 hover:text-slate-600 transition-colors"
              >
                <RefreshCw size={13} className={cn(loadingList && 'animate-spin')} />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loadingList ? (
              <div className="flex items-center gap-2 text-sm text-slate-500 p-4">
                <Loader2 size={14} className="animate-spin" />
                Loading…
              </div>
            ) : entries.length === 0 ? (
              <div className="p-4 text-sm text-slate-400 italic">
                No entries for {module} / {typeFilter}.
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {entries.map((e) => (
                  <li key={e.id || e.canonical_label} className="px-4 py-3 hover:bg-slate-50 group">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <span className={cn(
                            'inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded border uppercase tracking-wide',
                            typeColor(e.type)
                          )}>
                            {e.type}
                          </span>
                          <span className="text-sm font-medium text-slate-800 truncate">
                            {e.canonical_label}
                          </span>
                        </div>
                        <p className="text-xs text-slate-500 font-mono truncate">{e.technical_name}</p>
                        {e.synonyms && (
                          <p className="text-xs text-slate-400 truncate mt-0.5">{e.synonyms}</p>
                        )}
                      </div>
                      {e.id && (
                        <button
                          onClick={() => deleteEntry(e.id!, e.canonical_label)}
                          disabled={deletingId === e.id}
                          className="shrink-0 text-slate-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
                        >
                          {deletingId === e.id ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <Trash2 size={13} />
                          )}
                        </button>
                      )}
                    </div>
                    {e.updated_at && (
                      <p className="text-[10px] text-slate-300 mt-1">
                        {new Date(e.updated_at).toLocaleDateString()}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
