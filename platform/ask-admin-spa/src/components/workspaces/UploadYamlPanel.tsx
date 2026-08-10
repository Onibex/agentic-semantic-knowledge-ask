import { AlertTriangle, CheckCircle2, FileText, Loader2, Upload, X, XCircle } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { uploadYamlFile, type UploadYamlOutcome } from '@/api/client'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/hooks/useTranslation'

/**
 * Reusable multi-file YAML uploader — drag-drop or file picker → one
 * POST /v1/admin/yaml/import per file (up to 4 in parallel), with per-file
 * status (created / overwritten / conflict / invalid / error).
 *
 * Extracted from UploadYamlDialog so the same flow can be embedded both as a
 * standalone dialog (Graph page) and as a tab inside "New data product"
 * (Semantic Knowledge). The panel owns its file/running state + Upload button;
 * the host supplies only the surrounding chrome.
 *
 * Persistence boundary: each successful upload lands in the workspace folder
 * AND creates a git commit, but the runtime index is NOT touched — admins
 * still publish from the Deployment panel.
 */

interface Props {
  /** Triggered when at least one file landed successfully — host should refetch the catalogue. */
  onUploaded: (outcomes: UploadYamlOutcome[]) => void
  /** Lets the host disable its close affordance while a batch is in flight. */
  onBusyChange?: (busy: boolean) => void
}

interface FileRow {
  id: string
  file: File
  outcome?: UploadYamlOutcome
}

export function UploadYamlPanel({ onUploaded, onBusyChange }: Props) {
  const { t } = useTranslation()
  const [rows, setRows] = useState<FileRow[]>([])
  const [force, setForce] = useState(false)
  const [running, setRunning] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    onBusyChange?.(running)
  }, [running, onBusyChange])

  const addFiles = useCallback((files: FileList | File[]) => {
    const incoming = Array.from(files).filter(
      (f) =>
        f.name.endsWith('.yaml') ||
        f.name.endsWith('.yml') ||
        f.type === 'application/x-yaml' ||
        f.type === 'text/yaml',
    )
    if (incoming.length === 0) {
      toast.error('Only .yaml / .yml files are accepted')
      return
    }
    setRows((prev) => {
      const existing = new Set(prev.map((r) => r.file.name))
      const newRows = incoming
        .filter((f) => !existing.has(f.name))
        .map((f) => ({ id: crypto.randomUUID(), file: f }))
      return [...prev, ...newRows]
    })
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files)
    },
    [addFiles],
  )

  const removeRow = (id: string) => {
    setRows((prev) => prev.filter((r) => r.id !== id))
  }

  const handleUpload = useCallback(async () => {
    if (rows.length === 0) return
    setRunning(true)
    // Process up to 4 files in parallel — small enough that a stuck request
    // doesn't kill the batch, large enough to feel fast on 10+ files.
    const queue = [...rows]
    const updateOutcome = (rowId: string, outcome: UploadYamlOutcome) => {
      setRows((prev) => prev.map((r) => (r.id === rowId ? { ...r, outcome } : r)))
    }
    async function worker() {
      while (queue.length > 0) {
        const row = queue.shift()
        if (!row) return
        const outcome = await uploadYamlFile(row.file, force)
        updateOutcome(row.id, outcome)
      }
    }
    await Promise.all(Array.from({ length: Math.min(4, rows.length) }, worker))
    setRunning(false)

    // Tell the host only about the SUCCESSFUL ones — they need to refetch the
    // catalogue. Failures stay in the panel for the admin to inspect.
    const successful = rows
      .map((r) => r.outcome)
      .filter(
        (o): o is UploadYamlOutcome =>
          !!o && (o.status === 'created' || o.status === 'overwritten'),
      )
    if (successful.length > 0) {
      toast.success(
        `Uploaded ${successful.length} of ${rows.length} YAML${rows.length === 1 ? '' : 's'}`,
      )
      onUploaded(successful)
    } else {
      toast.error('No files were uploaded')
    }
  }, [rows, force, onUploaded])

  const allDone = rows.length > 0 && rows.every((r) => r.outcome)
  const summary = allDone
    ? {
        ok: rows.filter((r) => r.outcome?.status === 'created' || r.outcome?.status === 'overwritten').length,
        conflict: rows.filter((r) => r.outcome?.status === 'conflict').length,
        invalid: rows.filter((r) => r.outcome?.status === 'invalid').length,
        error: rows.filter((r) => r.outcome?.status === 'error').length,
      }
    : null

  return (
    <div className="space-y-3">
      {/* Dropzone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => fileInputRef.current?.click()}
        className={`flex flex-col items-center justify-center py-6 px-4 rounded-md border-2 border-dashed cursor-pointer transition-colors ${
          dragOver ? 'border-blue-400 bg-blue-50' : 'border-gray-300 bg-gray-50 hover:border-gray-400'
        }`}
      >
        <Upload size={20} className="text-gray-400 mb-1.5" />
        <p className="text-sm font-medium text-gray-700">{t('upload_dropzone_title')}</p>
        <p className="text-xs text-gray-500 mt-1">
          Multiple <code>.yaml</code> / <code>.yml</code> at once. The backend places each in the
          right <code>bronze/silver/gold/&lt;module&gt;</code> folder.
        </p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".yaml,.yml,application/x-yaml,text/yaml"
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
            if (fileInputRef.current) fileInputRef.current.value = ''
          }}
        />
      </div>

      {/* Overwrite toggle */}
      <label className="flex items-center gap-2 text-xs text-gray-700">
        <input
          type="checkbox"
          checked={force}
          onChange={(e) => setForce(e.target.checked)}
          disabled={running}
        />
        <span>{t('upload_overwrite_label')}</span>
      </label>

      {/* File list */}
      {rows.length > 0 && (
        <div className="border border-gray-200 rounded divide-y divide-gray-100 max-h-56 overflow-y-auto">
          {rows.map((row) => (
            <div key={row.id} className="flex items-start gap-2 px-2 py-1.5">
              <FileText size={14} className="text-gray-400 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-mono text-gray-800 truncate">{row.file.name}</div>
                {row.outcome ? (
                  <OutcomeLine outcome={row.outcome} />
                ) : (
                  <div className="text-[11px] text-gray-400">
                    {(row.file.size / 1024).toFixed(1)} kB · pending
                  </div>
                )}
              </div>
              {!running && !row.outcome && (
                <button
                  type="button"
                  onClick={() => removeRow(row.id)}
                  className="shrink-0 text-gray-400 hover:text-gray-700"
                  aria-label="Remove"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {summary && (
        <div className="px-3 py-2 rounded border border-gray-200 bg-gray-50 text-[11px] text-gray-600">
          ✓ {summary.ok} uploaded · {summary.conflict} conflict · {summary.invalid} invalid ·{' '}
          {summary.error} error
        </div>
      )}

      {!allDone && (
        <div className="flex justify-end">
          <Button onClick={() => void handleUpload()} disabled={rows.length === 0 || running}>
            {running ? (
              <>
                <Loader2 size={12} className="animate-spin mr-1.5" /> {t('upload_uploading')}
              </>
            ) : (
              rows.length === 1
                ? t('upload_btn').replace('{n}', String(rows.length))
                : t('upload_btn_plural').replace('{n}', String(rows.length))
            )}
          </Button>
        </div>
      )}
    </div>
  )
}

function OutcomeLine({ outcome }: { outcome: UploadYamlOutcome }) {
  const { t } = useTranslation()
  if (outcome.status === 'created' || outcome.status === 'overwritten') {
    return (
      <div className="flex items-center gap-1 text-[11px] text-emerald-700">
        <CheckCircle2 size={11} />
        <span>
          {outcome.status === 'overwritten' ? t('upload_overwritten') : t('upload_created')} as{' '}
          <code className="font-mono">{outcome.entity_id}</code> · layer: {outcome.layer}
        </span>
      </div>
    )
  }
  if (outcome.status === 'conflict') {
    return (
      <div className="flex items-start gap-1 text-[11px] text-amber-700">
        <AlertTriangle size={11} className="mt-0.5 shrink-0" />
        <span>{t('upload_conflict')}</span>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-1 text-[11px] text-red-700">
      <XCircle size={11} className="mt-0.5 shrink-0" />
      <span className="font-mono break-words">{outcome.message ?? 'Failed'}</span>
    </div>
  )
}
