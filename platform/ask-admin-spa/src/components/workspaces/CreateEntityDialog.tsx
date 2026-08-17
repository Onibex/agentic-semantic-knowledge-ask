import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { getOrganization, getSourceProfiles, importDdl, ingestSapJson } from '@/api/client'
import type { DdlImportResult, MergeResult, SourceProfile } from '@/api/types'
import { useAuthStore } from '@/store/authStore'
import { ManualEntityForm } from '@/components/workspaces/ManualEntityForm'
import { UploadYamlPanel } from '@/components/workspaces/UploadYamlPanel'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useTranslation } from '@/hooks/useTranslation'

/** Resolve an Organization source-system label (free text like "SAP S/4HANA
 * 2023") to a profile key. Mirrors the backend `get_profile` heuristic so the
 * dropdown defaults sensibly; the backend stays authoritative at import time. */
function resolveProfileKey(orgSource: string, profiles: SourceProfile[]): string {
  const raw = (orgSource || '').toLowerCase()
  const firstToken = raw.split(/[_\s]/)[0]
  const exact = profiles.find((p) => p.key === firstToken)
  if (exact) return exact.key
  if (raw.includes('ecc')) return 'ecc'
  if (raw.includes('s/4') || raw.includes('s4h') || raw.includes('s4hana') || raw.includes('sap'))
    return 's4h'
  if (raw.includes('salesforce') || raw.includes('sfdc')) return 'salesforce'
  if (raw.includes('odoo')) return 'odoo'
  return profiles[0]?.key ?? 's4h'
}

/**
 * Create / Import an entity (UX_CHANGES audit CH-6, Iter 6) — four modes:
 *   Manual         → structured authoring form (header + fields + relationships).
 *   Upload files   → drag-drop one or many .yaml files (multi-file import).
 *   DDL + AI       → paste SQL DDL; the AI maps it to ASK YAML at a chosen layer.
 *   From OneConnect → paste an SAP JSON export (the merge engine; "OneConnect"
 *                     is the external product that produces those JSONs, Q12).
 *
 * Every path lands the entity In Review; on success the parent refreshes the
 * Semantic Knowledge catalog filtered to In Review (the review queue).
 */
interface Props {
  open: boolean
  onClose: () => void
  onCreated: () => void
}

type Layer = 'bronze' | 'silver' | 'gold'
type LayerOrEmpty = Layer | ''

/** Detect the ASK layer from a DDL's CREATE TABLE name. Confident only on the
 * SILVER_/GOLD_ naming convention; otherwise '' (undetected) so the user must
 * pick — we never silently assume bronze (the old footgun). */
function detectLayer(ddl: string): LayerOrEmpty {
  const m = ddl.match(
    /\bcreate\s+(?:global\s+|local\s+)?(?:temp(?:orary)?\s+)?table\s+(?:if\s+not\s+exists\s+)?([^\s(]+)/i,
  )
  if (!m) return ''
  const name = (m[1].replace(/["`[\]]/g, '').split('.').pop() ?? '').toUpperCase()
  if (name.startsWith('SILVER_') || name.includes('_SILVER_')) return 'silver'
  if (name.startsWith('GOLD_') || name.includes('_GOLD_')) return 'gold'
  return ''
}

export function CreateEntityDialog({ open, onClose, onCreated }: Props) {
  const { t } = useTranslation()
  const email = useAuthStore((s) => s.user?.email ?? '')

  // DDL + AI
  const [ddlText, setDdlText] = useState('')
  const [pasteLayer, setPasteLayer] = useState<LayerOrEmpty>('') // layer for the pasted script
  const [sourceSystem, setSourceSystem] = useState('s4h')
  const [profiles, setProfiles] = useState<SourceProfile[]>([])
  const [sourceFromOrg, setSourceFromOrg] = useState(true) // default: derive from Organization
  const [overrideSource, setOverrideSource] = useState(false) // reveal the manual picker
  const [forceOverwrite, setForceOverwrite] = useState(false)
  // NOTE: there is deliberately no Module input. The backend auto-detects the
  // silver/gold `module` per relation from the physical table name
  // (`SILVER_SD_*` → `sd`) and falls back to `gen`; the author adjusts it in the
  // editor if needed (every import lands In Review anyway).
  const [ddlContext, setDdlContext] = useState('') // general context for the whole batch
  // Per-file: auto-detected layer (overridable), optional per-file note.
  const [ddlFileItems, setDdlFileItems] = useState<
    { file: File; text: string; layer: LayerOrEmpty; detected: boolean; note: string }[]
  >([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Live per-source progress (uploaded file or the pasted script): each goes
  // queued → running → done so the user sees the sequential pipeline advance.
  const [ddlProgress, setDdlProgress] = useState<
    { name: string; status: 'pending' | 'running' | 'done'; result?: DdlImportResult }[]
  >([])
  // OneConnect
  const [jsonText, setJsonText] = useState('')
  const [mergeResult, setMergeResult] = useState<MergeResult | null>(null)

  const [busy, setBusy] = useState(false)

  // Load source-system profiles + default the selection from the Organization
  // when the dialog opens (Phase C2/C4). Best-effort: falls back to s4h.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    void (async () => {
      try {
        const [profs, org] = await Promise.all([
          getSourceProfiles(),
          getOrganization().catch(() => null),
        ])
        if (cancelled) return
        setProfiles(profs)
        const orgSource = org?.source_system || org?.sap_version || ''
        setSourceSystem(resolveProfileKey(orgSource, profs))
        setSourceFromOrg(Boolean(orgSource))
      } catch {
        // Endpoint unavailable — keep the free 's4h' default; dropdown stays empty.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open])

  function reset() {
    setDdlText('')
    setPasteLayer('')
    setDdlContext('')
    setDdlFileItems([])
    if (fileInputRef.current) fileInputRef.current.value = ''
    setDdlProgress([])
    setForceOverwrite(false)
    setOverrideSource(false)
    setJsonText('')
    setMergeResult(null)
    setBusy(false) // never carry a stale in-flight flag into the next open
  }

  async function onPickFiles(fileList: FileList | null) {
    const files = Array.from(fileList ?? [])
    const items = await Promise.all(
      files.map(async (file) => {
        const text = await file.text()
        const detectedLayer = detectLayer(text)
        return { file, text, layer: detectedLayer, detected: detectedLayer !== '', note: '' }
      }),
    )
    setDdlFileItems(items)
  }

  function setFileLayer(idx: number, value: LayerOrEmpty) {
    setDdlFileItems((prev) => prev.map((it, i) => (i === idx ? { ...it, layer: value } : it)))
  }
  function setFileNote(idx: number, value: string) {
    setDdlFileItems((prev) => prev.map((it, i) => (i === idx ? { ...it, note: value } : it)))
  }
  function setUndetectedLayer(value: Layer) {
    setDdlFileItems((prev) => prev.map((it) => (it.layer === '' ? { ...it, layer: value } : it)))
  }

  async function handleDdl() {
    // Each source (uploaded .sql file, or the pasted script) is one DDL batch
    // mapped + imported with ITS OWN layer. Files take precedence over the paste.
    const sources: { name: string; text: string; layer: LayerOrEmpty; note: string }[] = []
    if (ddlFileItems.length > 0) {
      for (const f of ddlFileItems)
        sources.push({ name: f.file.name, text: f.text, layer: f.layer, note: f.note })
    } else if (ddlText.trim()) {
      sources.push({ name: 'pasted DDL', text: ddlText, layer: pasteLayer, note: '' })
    } else {
      toast.error('Select .sql file(s) or paste DDL first')
      return
    }

    // Hard guard: never import a source whose layer is still unset.
    const missing = sources.filter((s) => !s.layer)
    if (missing.length > 0) {
      toast.error(`Select a layer for: ${missing.map((s) => s.name).join(', ')}`)
      return
    }

    setBusy(true)
    // Seed the whole queue as pending so the user sees every file up-front and
    // watches each advance — no more "is it hung?" with a blank global spinner.
    setDdlProgress(sources.map((s) => ({ name: s.name, status: 'pending' as const })))
    const src = sourceSystem.trim() || 's4h'
    let created = 0
    let failed = 0
    try {
      for (let i = 0; i < sources.length; i++) {
        const s = sources[i]
        setDdlProgress((prev) => prev.map((p, j) => (j === i ? { ...p, status: 'running' } : p)))
        // General context + the file's own note (per-file precision).
        const ctx = [ddlContext.trim(), s.note.trim()].filter(Boolean).join('\n\n')
        let result: DdlImportResult
        try {
          result = await importDdl(s.text, s.layer as Layer, src, forceOverwrite, ctx)
          created += result.items.filter((it) => it.outcome !== 'error').length
          failed += result.items.filter((it) => it.outcome === 'error').length
        } catch (err: unknown) {
          // A whole-file failure (e.g. LLM 502) — surface it as a per-file error
          // row so one bad file never hides the rest.
          result = {
            generated_yaml: '',
            tokens_used: 0,
            items: [
              {
                entity_id: null,
                layer: null,
                file_path: null,
                outcome: 'error',
                reason: errDetail(err, 'DDL → YAML mapping failed'),
              },
            ],
            warnings: [],
          }
          failed += 1
        }
        // Mark done with its result the moment this file finishes (live update).
        setDdlProgress((prev) =>
          prev.map((p, j) => (j === i ? { ...p, status: 'done', result } : p)),
        )
      }
      const n = sources.length
      if (failed && !created) toast.error(`${failed} item(s) failed to import`)
      else
        toast.success(
          `Imported ${created} entity(ies)${failed ? `, ${failed} failed` : ''} from ${n} file(s)`,
        )
      if (created) onCreated()
    } finally {
      setBusy(false)
    }
  }

  async function handleOneConnect() {
    if (!jsonText.trim()) {
      toast.error('Paste an SAP JSON payload first')
      return
    }
    let payload: Record<string, unknown>
    try {
      payload = JSON.parse(jsonText)
    } catch {
      toast.error('Payload is not valid JSON')
      return
    }
    setBusy(true)
    setMergeResult(null)
    try {
      const r = await ingestSapJson(payload, email)
      setMergeResult(r)
      toast.success(
        `Merged ${r.silver_id}: ${r.auto_applied.length} auto-applied, ${r.conflicts.length} conflicts`,
      )
      onCreated()
    } catch (err: unknown) {
      toast.error(errDetail(err, 'OneConnect merge failed'))
    } finally {
      setBusy(false)
    }
  }

  // Block "Map + import" until every source has a layer — kills the silent-bronze
  // footgun: undetected files / a pasted script must have a layer chosen first.
  const someFileLayerUnset = ddlFileItems.length > 0 && ddlFileItems.some((f) => !f.layer)
  const pasteLayerUnset = ddlFileItems.length === 0 && ddlText.trim() !== '' && !pasteLayer
  const nothingToImport = ddlFileItems.length === 0 && ddlText.trim() === ''
  const importDisabled = busy || someFileLayerUnset || pasteLayerUnset || nothingToImport

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset()
          onClose()
        }
      }}
    >
      {/* max-h + overflow so the whole modal scrolls on small screens — the
          shadcn fix for tall dialogs (the Map + import button stays reachable). */}
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('ced_title')}</DialogTitle>
          <DialogDescription>{t('ced_desc')}</DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="upload" className="py-1">
          <TabsList>
            <TabsTrigger value="manual">{t('ced_tab_manual')}</TabsTrigger>
            <TabsTrigger value="upload">{t('ced_tab_upload')}</TabsTrigger>
            <TabsTrigger value="ddl">{t('ced_tab_ddl')}</TabsTrigger>
            <TabsTrigger value="oneconnect">{t('ced_tab_oneconnect')}</TabsTrigger>
          </TabsList>

          {/* Upload files — multi-file .yaml import (shares the Graph uploader) */}
          <TabsContent value="upload" className="space-y-3">
            <p className="text-xs text-gray-500">{t('ced_upload_tab_desc')}</p>
            <UploadYamlPanel onUploaded={() => onCreated()} />
          </TabsContent>

          {/* Manual — structured authoring form (Standards-aligned) */}
          <TabsContent value="manual">
            <ManualEntityForm onCreated={onCreated} onClose={onClose} />
          </TabsContent>

          {/* DDL + AI */}
          <TabsContent value="ddl" className="space-y-3">
            <div className="flex items-end gap-3">
              <div className="space-y-1">
                <Label>{t('ced_ddl_source_label')}</Label>
                {overrideSource ? (
                  <select
                    value={sourceSystem}
                    onChange={(e) => setSourceSystem(e.target.value)}
                    className="block w-44 rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm"
                  >
                    {/* Keep the resolved value selectable even if the profile list
                        didn't load (offline) — the backend resolves it anyway. */}
                    {profiles.length === 0 && <option value={sourceSystem}>{sourceSystem}</option>}
                    {profiles.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="flex h-[34px] items-center gap-2">
                    <span className="rounded-md bg-gray-100 px-2 py-1.5 text-sm text-gray-700">
                      {profiles.find((p) => p.key === sourceSystem)?.label ?? sourceSystem}
                    </span>
                    <button
                      type="button"
                      onClick={() => setOverrideSource(true)}
                      className="text-xs text-gray-400 underline hover:text-gray-600"
                    >
                      {t('ced_ddl_change')}
                    </button>
                  </div>
                )}
                <p className="text-[10px] text-gray-400">
                  {overrideSource
                    ? t('ced_ddl_overriding')
                    : sourceFromOrg
                      ? t('ced_ddl_from_org')
                      : t('ced_ddl_set_in_org')}
                </p>
              </div>
            </div>
            {/* Multi-file .sql upload — layer auto-detected per file from the
                CREATE TABLE name; undetected files must be set before import. */}
            <div className="space-y-2">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".sql,.ddl,.txt"
                onChange={(e) => void onPickFiles(e.target.files)}
                className="block w-full text-xs text-gray-600 file:mr-3 file:rounded-md file:border-0 file:bg-gray-100 file:px-3 file:py-1.5 file:text-xs file:font-medium hover:file:bg-gray-200"
              />
              {ddlFileItems.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-[11px] text-gray-500">
                    <span>{t('ced_ddl_files_n').replace('{n}', String(ddlFileItems.length))}</span>
                    <div className="flex items-center gap-1.5">
                      {someFileLayerUnset && (
                        <>
                          <span className="text-amber-700">{t('ced_ddl_set_undetected')}</span>
                          {(['bronze', 'silver', 'gold'] as Layer[]).map((l) => (
                            <button
                              key={l}
                              type="button"
                              onClick={() => setUndetectedLayer(l)}
                              className="rounded border border-gray-300 px-1.5 py-0.5 capitalize hover:bg-gray-100"
                            >
                              {l}
                            </button>
                          ))}
                          <span className="text-gray-300">·</span>
                        </>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          setDdlFileItems([])
                          if (fileInputRef.current) fileInputRef.current.value = ''
                        }}
                        className="text-gray-400 underline hover:text-gray-600"
                      >
                        {t('ced_ddl_clear')}
                      </button>
                    </div>
                  </div>
                  <div className="rounded-md border border-gray-200 divide-y divide-gray-100">
                    {ddlFileItems.map((f, i) => (
                      <div key={`${f.file.name}-${i}`} className="space-y-1 px-2 py-1.5">
                        <div className="flex items-center gap-2 text-xs">
                          <code className="flex-1 truncate font-mono text-gray-700">
                            {f.file.name}
                          </code>
                          {f.detected ? (
                            <span className="text-[10px] text-green-600">detected</span>
                          ) : (
                            <span className="text-[10px] text-amber-600">pick layer</span>
                          )}
                          <select
                            value={f.layer}
                            onChange={(e) => setFileLayer(i, e.target.value as LayerOrEmpty)}
                            className={`rounded-md border px-1.5 py-1 text-xs ${
                              f.layer ? 'border-gray-300 bg-white' : 'border-amber-400 bg-amber-50'
                            }`}
                          >
                            <option value="">— select —</option>
                            <option value="bronze">Bronze</option>
                            <option value="silver">Silver</option>
                            <option value="gold">Gold</option>
                          </select>
                        </div>
                        <input
                          type="text"
                          value={f.note}
                          onChange={(e) => setFileNote(i, e.target.value)}
                          placeholder="Per-file note (optional) — appended to the context below"
                          className="w-full rounded border border-gray-200 px-2 py-1 text-[11px]"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            {/* Paste fallback — single script. Layer auto-detected, else required. */}
            <div className="space-y-1.5">
              <textarea
                value={ddlText}
                onChange={(e) => {
                  const v = e.target.value
                  setDdlText(v)
                  const d = detectLayer(v)
                  if (d) setPasteLayer(d)
                }}
                rows={6}
                disabled={ddlFileItems.length > 0}
                placeholder={
                  ddlFileItems.length > 0
                    ? 'Using uploaded files (clear them to paste instead)'
                    : '…or paste a single DDL script:\nCREATE TABLE VBAK (\n  VBELN VARCHAR(10) PRIMARY KEY,\n  NETWR DECIMAL(15,2)\n);'
                }
                className="w-full px-3 py-2 rounded-md border border-gray-300 bg-white text-xs font-mono resize-none disabled:bg-gray-50 disabled:text-gray-400"
              />
              {ddlFileItems.length === 0 && ddlText.trim() !== '' && (
                <div className="flex items-center gap-2 text-xs">
                  <Label className="text-xs text-gray-600">Layer</Label>
                  <select
                    value={pasteLayer}
                    onChange={(e) => setPasteLayer(e.target.value as LayerOrEmpty)}
                    className={`rounded-md border px-1.5 py-1 text-xs ${
                      pasteLayer ? 'border-gray-300 bg-white' : 'border-amber-400 bg-amber-50'
                    }`}
                  >
                    <option value="">— select —</option>
                    <option value="bronze">Bronze</option>
                    <option value="silver">Silver</option>
                    <option value="gold">Gold</option>
                  </select>
                  {!pasteLayer && <span className="text-[10px] text-amber-600">required</span>}
                </div>
              )}
            </div>
            {/* General business context for ALL files — enriches the prompt. */}
            <div className="space-y-1">
              <Label className="text-xs text-gray-600">{t('ced_ddl_context_label')}</Label>
              <textarea
                value={ddlContext}
                onChange={(e) => setDdlContext(e.target.value)}
                rows={2}
                placeholder="What are these tables for? e.g. 'SAP PP production order tables — used for shop-floor throughput and yield reporting.' Applied to every file; per-file notes above are appended."
                className="w-full px-3 py-2 rounded-md border border-gray-300 bg-white text-xs resize-none"
              />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-gray-400">
                {t('ced_ddl_maps_hint').replace('{source}', sourceSystem)}
              </span>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1.5 text-xs text-gray-600 select-none">
                  <input
                    type="checkbox"
                    checked={forceOverwrite}
                    onChange={(e) => setForceOverwrite(e.target.checked)}
                  />
                  {t('ced_ddl_overwrite')}
                </label>
                <Button onClick={() => void handleDdl()} disabled={importDisabled}>
                  {busy && <Loader2 size={12} className="animate-spin mr-1.5" />}
                  {t('ced_ddl_map_import_btn')}
                </Button>
              </div>
            </div>
            {ddlProgress.length > 0 && (
              <div className="space-y-3 max-h-72 overflow-y-auto">
                {/* Live overall counter while running */}
                {busy && (
                  <div className="text-[11px] text-gray-500">
                    Processing {ddlProgress.filter((p) => p.status === 'done').length}/
                    {ddlProgress.length}…
                  </div>
                )}
                {ddlProgress.map((p, gi) => {
                  const r = p.result
                  const okCount = r ? r.items.filter((it) => it.outcome !== 'error').length : 0
                  const errCount = r ? r.items.filter((it) => it.outcome === 'error').length : 0
                  const allFailed = !!r && errCount > 0 && okCount === 0
                  return (
                    <div key={`${p.name}-${gi}`} className="space-y-1.5">
                      <div className="flex items-center gap-2 text-xs font-semibold text-gray-700">
                        {p.status === 'running' && (
                          <Loader2 size={12} className="animate-spin text-blue-500 shrink-0" />
                        )}
                        {p.status === 'pending' && <span className="text-gray-300">○</span>}
                        {p.status === 'done' && (
                          <span className={allFailed ? 'text-red-600' : 'text-green-600'}>
                            {allFailed ? '✗' : '✓'}
                          </span>
                        )}
                        <span className="truncate">{p.name}</span>
                        {p.status === 'running' && (
                          <span className="font-normal text-blue-500">processing…</span>
                        )}
                        {p.status === 'pending' && (
                          <span className="font-normal text-gray-400">queued</span>
                        )}
                        {p.status === 'done' && (
                          <span className="font-normal text-gray-400">
                            {okCount} ok{errCount ? `, ${errCount} failed` : ''}
                          </span>
                        )}
                      </div>
                      {r && r.warnings && r.warnings.length > 0 && (
                        <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
                          {r.warnings.map((w, i) => (
                            <div key={i}>⚠ {w}</div>
                          ))}
                        </div>
                      )}
                      {r && (
                        <div className="rounded-md border border-gray-200 divide-y divide-gray-100">
                          {r.items.map((it, i) => (
                            <div key={i} className="flex items-center gap-2 px-2 py-1 text-xs">
                              <span
                                className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                                  it.outcome === 'error'
                                    ? 'bg-red-100 text-red-700'
                                    : 'bg-green-100 text-green-700'
                                }`}
                              >
                                {it.outcome}
                              </span>
                              <code className="font-mono text-gray-700 truncate">
                                {it.entity_id ?? '(unparsed)'}
                              </code>
                              {it.reason && (
                                <span className="text-gray-400 truncate">— {it.reason}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      {r && r.generated_yaml && (
                        <details className="text-xs">
                          <summary className="cursor-pointer text-gray-500">Generated YAML</summary>
                          <pre className="mt-1 max-h-48 overflow-auto rounded bg-gray-50 border border-gray-200 p-2 text-[11px] font-mono whitespace-pre-wrap">
                            {r.generated_yaml}
                          </pre>
                        </details>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </TabsContent>

          {/* From OneConnect */}
          <TabsContent value="oneconnect" className="space-y-3">
            <p className="text-xs text-gray-500">
              {t('ced_oc_desc')}
            </p>
            <textarea
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              rows={10}
              placeholder={'{ "info": { ... }, "columns": [ ... ], "relations": [ ... ] }'}
              className="w-full px-3 py-2 rounded-md border border-gray-300 bg-white text-xs font-mono resize-none"
            />
            <div className="flex justify-end">
              <Button onClick={() => void handleOneConnect()} disabled={busy}>
                {busy && <Loader2 size={12} className="animate-spin mr-1.5" />}
                {t('ced_oc_merge_btn')}
              </Button>
            </div>
            {mergeResult && (
              <div className="rounded-md border border-gray-200 bg-gray-50 p-2 text-xs text-gray-700">
                <div className="font-mono">{mergeResult.silver_id}</div>
                <div className="text-gray-500 mt-1">
                  {mergeResult.auto_applied.length} auto-applied · {mergeResult.conflicts.length}{' '}
                  conflicts
                  {mergeResult.conflicts.length > 0 ? ` ${t('ced_oc_resolve_hint')}` : ''}
                </div>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

function errDetail(err: unknown, fallback: string): string {
  const ax = err as { response?: { data?: { detail?: string } }; message?: string }
  return ax.response?.data?.detail ?? ax.message ?? fallback
}
